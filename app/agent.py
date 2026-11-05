"""Agent layer.

Three pieces, all agent-agnostic:
  * context: the app's data as compact Markdown that any model can read (also served to the `openticker` CLI)
  * skills: SKILL.md files in ./skills (the open Agent Skills format), usable in-app or installed into
    Claude Code, Codex, Cursor, opencode or Gemini CLI
  * ask: runs the user's own agent CLI (so their existing subscription pays) or a local Ollama model,
    and streams the answer back to the page

server.py calls bind(sys.modules[__name__]) at start; everything here reads the server's state through `srv`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

import paths  # noqa: E402

HERE = paths.APP
SKILLS_DIR = paths.SKILLS
BIN_DIR = paths.BIN
WORK_DIR = paths.DATA / "agent-work"     # empty scratch folder the agent runs in, so it can't touch the app
APP_NAME = "OpenTicker"
srv = None


def bind(module):
    global srv
    srv = module
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (BIN_DIR / "openticker").chmod(0o755)    # file copies can drop the executable bit
    except Exception:
        pass


# ---------------------------------------------------------------- formatting helpers
def _pct(x, d=1, sign=True):
    if x is None:
        return "n/a"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def _money(x):
    if x is None:
        return "n/a"
    a = abs(x)
    s = "-" if x < 0 else ""
    if a >= 1e12:
        return f"{s}${a / 1e12:.2f}T"
    if a >= 1e9:
        return f"{s}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{s}${a / 1e6:.1f}M"
    if a >= 1000 or a == 0:
        return f"{s}${a:,.0f}"
    return f"{s}${a:,.2f}"


def _n(k, word, plural=None):
    return f"{k} {word if k == 1 else plural or word + 's'}"


def _num(x, d=1, suffix=""):
    return "n/a" if x is None else f"{x:.{d}f}{suffix}"


def _table(head, rows):
    if not rows:
        return ""
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _now_ny():
    return dt.datetime.now(srv.NY).strftime("%a %b %-d %Y, %-I:%M %p New York time")


# ---------------------------------------------------------------- price math from the server's daily closes
HORIZONS = (("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252))


def _series(sym):
    with srv.S.lock:
        return list(srv.S.dates), list(srv.S.px.get(sym) or [])


def _ret(arr, n):
    if len(arr) <= n or arr[-1] is None:
        return None
    base = next((v for v in reversed(arr[:len(arr) - n]) if v is not None), None)
    return arr[-1] / base - 1 if base else None


def _ytd(dates, arr):
    if not arr or arr[-1] is None:
        return None
    y = dates[-1][:4]
    idx = next((i for i, d in enumerate(dates) if d[:4] == y), None)
    if not idx:
        return None
    base = next((v for v in reversed(arr[:idx]) if v is not None), None)
    return arr[-1] / base - 1 if base else None


def _trim(arr):
    """Drop the empty rows Yahoo leaves at the end of a daily series before a day's first trade."""
    arr = list(arr)
    while arr and arr[-1] is None:
        arr.pop()
    return arr


def _avg(arr, n):
    xs = [v for v in arr[-n:] if v is not None]
    return sum(xs) / len(xs) if len(xs) >= n * 0.8 else None


def price_lines(sym, bench="SPY"):
    dates, arr = _series(sym)
    if not arr or arr[-1] is None:
        return []
    _, b = _series(bench)
    last = arr[-1]
    rows = []
    for lab, n in HORIZONS:
        r, rb = _ret(arr, n), _ret(b, n)
        rows.append([lab, _pct(r), _pct(rb), _pct(r - rb) if r is not None and rb is not None else "n/a"])
    r, rb = _ytd(dates, arr), _ytd(dates, b)
    rows.insert(5, ["YTD", _pct(r), _pct(rb), _pct(r - rb) if r is not None and rb is not None else "n/a"])
    out = [f"Last price ${last:,.2f} (session {dates[-1]})."]
    with srv.S.lock:
        x = srv.S.ext_view().get(sym)
    if x:
        lab = "Pre-market" if x[2] == "pre" else "After hours"
        when = dt.datetime.fromtimestamp(x[1], srv.NY).strftime("%-I:%M %p")
        out.append(f"{lab}: ${x[0]:,.2f}, {_pct(x[3])} from the last close, as of {when} New York time "
                   "(thin trading outside the regular session; the open can differ).")
    a50, a200 = _avg(arr, 50), _avg(arr, 200)
    yr = [v for v in arr[-252:] if v is not None]
    bits = []
    if a50:
        bits.append(f"{_pct(last / a50 - 1)} vs 50-day average (${a50:,.2f})")
    if a200:
        bits.append(f"{_pct(last / a200 - 1)} vs 200-day average (${a200:,.2f})")
    if yr:
        hi, lo = max(yr), min(yr)
        bits.append(f"52-week range ${lo:,.2f} to ${hi:,.2f}, now {_pct(last / hi - 1)} from the high")
    if bits:
        out.append("Trend: " + "; ".join(bits) + ".")
    daily = [arr[i] / arr[i - 1] - 1 for i in range(max(1, len(arr) - 63), len(arr)) if arr[i] and arr[i - 1]]
    if len(daily) > 20:
        sd = (sum(x * x for x in daily) / len(daily)) ** 0.5
        out.append(f"Typical daily move over 3 months: ±{sd * 100:.1f}% (annualized volatility about {sd * 252 ** 0.5 * 100:.0f}%).")
    out.append("")
    out.append(_table(["Period", sym, bench, "Difference"], rows))
    return out


def fund_membership(sym):
    out = []
    for f, name in srv.FUNDS.items():
        for h in (srv.S.holdings.get(f) or {}).get("holdings", []):
            if h["t"] == sym:
                out.append(f"{f} {h['w']:.2f}%")
    return out


# ---------------------------------------------------------------- research fetches (cached by the server)
def _fetch(name, sym):
    if name == "detail":
        return srv.stock_detail(sym)
    if name == "earnhist":
        return srv.earnings_history(sym)
    return srv.extra(name, {"t": [sym]})


def _cache_key(name, sym):
    return {"detail": ("info", sym), "earnhist": ("earnhist", sym)}.get(name, ("x", name, sym, ()))


def gather(sym, names, timeout=25):
    """Fetch several research blocks in parallel; whatever isn't back in time is reported as missing."""
    out = {}
    with ThreadPoolExecutor(max_workers=len(names)) as ex:
        futs = {ex.submit(_fetch, n, sym): n for n in names}
        done, _ = wait(futs, timeout=timeout)
        for f in done:
            try:
                out[futs[f]] = f.result()
            except Exception:
                pass
    return out


# ---------------------------------------------------------------- sections
def sec_company(info):
    if not info:
        return []
    L = []
    who = " · ".join(x for x in (info.get("sector"), info.get("industry")) if x)
    if who:
        L.append(f"Sector: {who}.")
    v = []
    if info.get("marketCap"):
        v.append(f"market cap {_money(info['marketCap'])}")
    if info.get("trailingPE"):
        v.append(f"P/E {info['trailingPE']:.1f}× trailing")
    if info.get("forwardPE"):
        v.append(f"{info['forwardPE']:.1f}× forward")
    if info.get("priceToSalesTrailing12Months"):
        v.append(f"price/sales {info['priceToSalesTrailing12Months']:.1f}×")
    if info.get("trailingPegRatio"):
        v.append(f"PEG {info['trailingPegRatio']:.2f}")
    if info.get("beta"):
        v.append(f"beta {info['beta']:.2f}")
    if v:
        L.append("Valuation: " + ", ".join(v) + ".")
    g = []
    for k, lab in (("revenueGrowth", "revenue growth (last quarter, year over year)"), ("earningsGrowth", "earnings growth"),
                   ("grossMargins", "gross margin"), ("operatingMargins", "operating margin"), ("profitMargins", "net margin"),
                   ("returnOnEquity", "return on equity")):
        if info.get(k) is not None:
            g.append(f"{lab} {_pct(info[k], 1, sign=k.endswith('Growth'))}")
    if g:
        L.append("Fundamentals: " + ", ".join(g) + ".")
    o = []
    if info.get("totalRevenue"):
        o.append(f"revenue (12 months) {_money(info['totalRevenue'])}")
    if info.get("freeCashflow"):
        o.append(f"free cash flow {_money(info['freeCashflow'])}")
    if info.get("dividendYield"):
        dy = info["dividendYield"]
        o.append(f"dividend yield {dy:.2f}%" if dy > 0.2 else f"dividend yield {dy * 100:.2f}%")
    if info.get("shortPercentOfFloat"):
        o.append(f"short interest {_pct(info['shortPercentOfFloat'], 1, False)} of float")
    if info.get("heldPercentInstitutions"):
        o.append(f"institutions hold {_pct(info['heldPercentInstitutions'], 0, False)}")
    if o:
        L.append("Other: " + ", ".join(o) + ".")
    if info.get("longBusinessSummary"):
        s = info["longBusinessSummary"]
        L.append("Business: " + (s[:600] + "…" if len(s) > 600 else s))
    return L


def sec_analysts(a, info, price):
    L = []
    if info.get("recommendationKey"):
        L.append(f"Consensus: {info['recommendationKey'].replace('_', ' ')} (mean {info.get('recommendationMean') or 'n/a'} on a 1 = strong buy to 5 = sell scale), "
                 f"{info.get('numberOfAnalystOpinions') or '?'} analysts.")
    t = (a or {}).get("targets") or {}
    mean = t.get("mean") or info.get("targetMeanPrice")
    if mean:
        up = f", {_pct(mean / price - 1, 0)} from here" if price else ""
        L.append(f"Price targets: mean ${mean:,.2f}{up}; range ${(t.get('low') or info.get('targetLowPrice') or 0):,.0f} to ${(t.get('high') or info.get('targetHighPrice') or 0):,.0f}.")
    if not a:
        return L
    tr = (a.get("trend") or [])[:1]
    if tr:
        r = tr[0]
        L.append(f"Ratings now: {r.get('strongBuy', 0)} strong buy, {r.get('buy', 0)} buy, {r.get('hold', 0)} hold, {r.get('sell', 0)} sell, {r.get('strongSell', 0)} strong sell.")
    ch = [c for c in a.get("changes") or [] if c.get("date")][:10]
    if ch:
        rows = []
        for c in ch:
            pt = f"${c['pt']:,.0f}" + (f" (was ${c['ptPrior']:,.0f})" if c.get("ptPrior") and c["ptPrior"] != c.get("pt") else "") if c.get("pt") else ""
            grade = (f"{c['from']} → " if c.get("from") and c.get("from") != c.get("to") else "") + (c.get("to") or "")
            rows.append([c["date"], c.get("firm") or "", c.get("action") or "", grade, pt])
        L += ["", "Recent rating and target changes:", _table(["Date", "Firm", "Action", "Rating", "Target"], rows), ""]
    et = a.get("eps_trend") or {}
    rows = []
    for p, lab in (("0q", "This quarter"), ("+1q", "Next quarter"), ("0y", "This year"), ("+1y", "Next year")):
        r = et.get(p) or {}
        if r.get("current"):
            chg = lambda k: _pct(r["current"] / r[k] - 1) if r.get(k) else "n/a"
            rows.append([lab, f"${r['current']:.2f}", chg("30daysAgo"), chg("90daysAgo")])
    if rows:
        L += ["EPS estimate trend:", _table(["Period", "EPS estimate", "vs 30 days ago", "vs 90 days ago"], rows), ""]
    ee, re_ = a.get("earnings_estimate") or {}, a.get("revenue_estimate") or {}
    rows = []
    for p, lab in (("0q", "This quarter"), ("0y", "This year"), ("+1y", "Next year")):
        e, r = ee.get(p) or {}, re_.get(p) or {}
        if e.get("avg") or r.get("avg"):
            rows.append([lab, f"${e['avg']:.2f}" if e.get("avg") else "n/a", _pct(e.get("growth")) if e.get("growth") is not None else "n/a",
                         _money(r.get("avg")), _pct(r.get("growth")) if r.get("growth") is not None else "n/a"])
    if rows:
        L += ["Estimates:", _table(["Period", "EPS", "EPS growth", "Revenue", "Revenue growth"], rows)]
    return L


def sec_earnings(sym, hist, opts):
    L = []
    e = srv.earnings_info(sym)
    if e.get("date"):
        timing = e.get("timing")
        if not timing and hist:      # the company's usual time of day, from past reports
            timing = "AMC" if (hist[0].get("hour") or 0) >= 12 else "BMO"
        when = {"BMO": "before the open", "AMC": "after the close"}.get(timing, "")
        today = dt.date.today().isoformat()
        known = next((h for h in hist or [] if h.get("date") == e["date"] and h.get("eps") is not None), None)
        est = (f", EPS estimate ${e['epsEst']:.2f}" if e.get("epsEst") else "") + (f", revenue estimate {_money(e['revEst'])}" if e.get("revEst") else "")
        if e.get("reported") is None and not known and e["date"] > today:
            L.append(f"Next earnings: {e['date']} {when}".rstrip() + est + ".")
        elif e.get("reported") is None and not known:
            L.append(f"Reported {'today' if e['date'] == today else 'on ' + e['date']} {when}".rstrip() + est
                     + ". Yahoo hasn't posted the results yet: check the news or the company's release for the numbers.")
        else:
            rep = e.get("reported") if e.get("reported") is not None else (known or {}).get("eps")
            L.append(f"Last reported {e['date']}" + (f": EPS ${rep:.2f} vs ${e['epsEst']:.2f} expected" if rep is not None and e.get("epsEst") else "") + ".")
    em = (opts or {}).get("earnings") or {}
    if em.get("move"):
        L.append(f"Options price a ±{em['move'] * 100:.1f}% move through the {em.get('expiry')} expiry, which covers earnings.")
    rows, moves, beats, n = [], [], 0, 0
    dates, arr = _series(sym)
    for h in (hist or [])[:12]:
        if h.get("eps") is None:
            continue
        rx = rx5 = ""
        if h["date"] in dates:   # the first session that could react (the same day for a report before the open)
            i = dates.index(h["date"]) + (1 if (h.get("hour") or 0) >= 12 else 0)
            if 0 < i < len(arr) and arr[i] and arr[i - 1]:
                moves.append(arr[i] / arr[i - 1] - 1)
                rx = _pct(moves[-1])
                if i + 4 < len(arr) and arr[i + 4]:
                    rx5 = _pct(arr[i + 4] / arr[i - 1] - 1)
        if h.get("epsEst") is not None:
            n += 1
            beats += h["eps"] > h["epsEst"]
        rows.append([h["date"], f"${h['eps']:.2f}", f"${h['epsEst']:.2f}" if h.get("epsEst") is not None else "n/a",
                     _pct(h["surprise"] / 100) if h.get("surprise") is not None else "n/a", rx or "n/a", rx5 or "n/a"])
        if len(rows) >= 8:
            break
    if rows:
        L += ["", "Earnings history:", _table(["Date", "EPS", "Expected", "Surprise", "Stock next session", "After 5 sessions"], rows)]
    if moves:
        avg = sum(abs(x) for x in moves) / len(moves)
        L.append(f"Beat the EPS estimate {beats} of {n} times. Average next-session move ±{avg * 100:.1f}% (largest {_pct(max(moves, key=abs))}); "
                 f"up {sum(1 for x in moves if x > 0)} of {len(moves)} times."
                 + (f" Options now price ±{em['move'] * 100:.1f}%, {'more' if em['move'] > avg * 1.1 else 'less' if em['move'] < avg * 0.9 else 'about the same'} than the average past move." if em.get("move") else ""))
    L.append("For revenue, margins and the latest quarter's numbers, see `openticker financials`; for guidance, check the news or the company's release.")
    return L


def sec_ownership(o):
    if not o:
        return []
    L = []
    m = o.get("major") or {}
    if m:
        bits = [f"{k.replace('PercentHeld', ' %').replace('Count', ' count')}: {v:.2%}" if isinstance(v, float) and v < 1.5 else f"{k}: {v}" for k, v in m.items()]
        L.append("Holders: " + "; ".join(bits) + ".")
    today = dt.date.today()
    tx = o.get("insiders") or []

    def within(x, n):
        try:
            return (today - dt.date.fromisoformat(x["date"][:10])).days <= n
        except Exception:
            return False
    for n in (90, 365):
        b = [x for x in tx if x.get("kind") == "buy" and within(x, n)]
        s = [x for x in tx if x.get("kind") == "sell" and within(x, n)]
        L.append(f"Insiders, last {n} days: {len(b)} open-market buys ({_money(sum(x.get('value') or 0 for x in b))}), "
                 f"{len(s)} sales ({_money(sum(x.get('value') or 0 for x in s))}).")
    rows = [[x["date"], str(x.get("insider") or "").title(), x.get("role") or "", x["kind"], _money(x.get("value")) if x.get("value") else ""]
            for x in tx if x.get("kind") in ("buy", "sell")][:8]
    if rows:
        L += ["", _table(["Date", "Insider", "Role", "Trade", "Value"], rows)]
    inst = o.get("institutions") or []
    if inst:
        L.append("Top institutions: " + "; ".join(f"{i['holder']} {(i.get('pct') or 0) * 100:.1f}%" + (f" ({_pct(i['chg'])} last filing)" if i.get("chg") is not None else "") for i in inst[:5]) + ".")
    return L


# ---------------------------------------------------------------- technicals (computed from daily bars)
def _sma_at(xs, n, end):
    """Average of the n values ending at index `end` (inclusive), or None."""
    if end + 1 < n:
        return None
    return sum(xs[end + 1 - n:end + 1]) / n


def _ema(xs, n):
    k, out, e = 2 / (n + 1), [], None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def _rsi(c, n=14):
    """Wilder's RSI, the standard 14-day setting."""
    if len(c) <= n:
        return []
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    lo = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    def rsi(ag, al):
        return 100 if al == 0 else 100 - 100 / (1 + ag / al)
    # g[i] is the change into close i + 1, so the first RSI (the plain average of 14 changes) belongs to close 14
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    out = [None] * n + [rsi(ag, al)]
    for i in range(n, len(g)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + lo[i]) / n
        out.append(rsi(ag, al))
    return out


def _levels(h, l, c, d, look=126, w=5, tol=0.015):
    """Support and resistance from swing points: a bar whose high (low) is the highest (lowest) of the w bars on
    each side. Swings within 1.5% of each other are one level; more touches make a level stronger."""
    n = len(c)
    pts = []
    for i in range(max(w, n - look), n - w):
        if h[i] == max(h[i - w:i + w + 1]):
            pts.append((h[i], d[i]))
        if l[i] == min(l[i - w:i + w + 1]):
            pts.append((l[i], d[i]))
    pts.sort()
    groups = []
    for p, day in pts:
        if groups and p <= groups[-1]["avg"] * (1 + tol):
            g = groups[-1]
            g["px"].append(p)
            g["avg"] = sum(g["px"]) / len(g["px"])
            g["last"] = max(g["last"], day)
        else:
            groups.append({"px": [p], "avg": p, "last": day})
    return [(g["avg"], len(g["px"]), g["last"]) for g in groups]


def _sector_etf(info):
    key = str(info.get("sector") or "").lower().replace(" ", "-")
    return next((e for e, _, k in srv.X.SECTOR_ETFS if k == key), None)


def sec_technicals(sym, b, info):
    if not b or len(b.get("c") or []) < 60:
        return []
    d, o, h, l, c, v = b["d"], b["o"], b["h"], b["l"], b["c"], [x or 0 for x in b["v"]]
    n, last = len(c), c[-1]
    L = [f"Last close ${last:,.2f} on {d[-1]}. Computed from {n} daily bars (split-adjusted)."]

    # trend: the averages, their direction over two weeks, and where price sits
    rows, avg = [], {}
    for k in (20, 50, 200):
        a, prev = _sma_at(c, k, n - 1), _sma_at(c, k, n - 11)
        if a is None:
            continue
        avg[k] = a
        slope = a / prev - 1 if prev else None
        way = "n/a" if slope is None else "rising" if slope > 0.005 else "falling" if slope < -0.005 else "flat"
        rows.append([f"{k}-day", f"${a:,.2f}", _pct(last / a - 1), f"{way} ({_pct(slope)} in 10 sessions)" if slope is not None else way])
    a20, a50, a200 = avg.get(20), avg.get(50), avg.get(200)
    if a50 and a200:
        s50 = _sma_at(c, 50, n - 11)
        up50 = s50 and a50 > s50
        if last > a50 > a200 and up50:
            trend = "Uptrend: price above a rising 50-day, which is above the 200-day."
        elif last < a50 < a200 and not up50:
            trend = "Downtrend: price below a falling 50-day, which is below the 200-day."
        elif a50 > a200 and last < a50:
            trend = "Pullback within an uptrend: the 50-day is still above the 200-day, but price has slipped under the 50-day."
        elif a50 < a200 and last > a50:
            trend = "Bounce within a downtrend: price is back above the 50-day, but the 50-day is still under the 200-day."
        else:
            trend = "Mixed: the averages don't agree."
        L.append("Trend: " + trend)
    L += ["", _table(["Average", "Level", "Price vs it", "Direction"], rows)]

    # the last golden or death cross (50-day crossing the 200-day)
    if n >= 210:
        diff = [(_sma_at(c, 50, i) or 0) - (_sma_at(c, 200, i) or 0) for i in range(199, n)]
        for j in range(len(diff) - 1, 0, -1):
            if (diff[j] > 0) != (diff[j - 1] > 0):
                i = j + 199
                L.append(f"Last cross: {'golden cross (50-day above 200-day)' if diff[j] > 0 else 'death cross (50-day below 200-day)'} on {d[i]}, {n - 1 - i} sessions ago.")
                break
        else:
            L.append(f"No 50/200-day cross in the last {n - 200} sessions; the 50-day has stayed {'above' if diff[-1] > 0 else 'below'} the 200-day.")

    # momentum
    r = _rsi(c)
    if r and r[-1] is not None:
        tag = "overbought (above 70)" if r[-1] >= 70 else "oversold (below 30)" if r[-1] <= 30 else "neutral (30 to 70)"
        L.append(f"RSI (14-day): {r[-1]:.0f}, {tag}; it was {r[-6]:.0f} five sessions ago." if r[-6] is not None else f"RSI (14-day): {r[-1]:.0f}, {tag}.")
    e12, e26 = _ema(c, 12), _ema(c, 26)
    macd = [a - b2 for a, b2 in zip(e12, e26)]
    sig = _ema(macd, 9)
    hist = [m - s for m, s in zip(macd, sig)]
    cross = next((i for i in range(n - 1, max(n - 61, 1), -1) if (hist[i] > 0) != (hist[i - 1] > 0)), None)
    L.append(f"MACD (12, 26, 9): {macd[-1]:+.2f}, signal {sig[-1]:+.2f}, so momentum is {'above' if hist[-1] > 0 else 'below'} its signal line"
             + (f"; it crossed {'up' if hist[cross] > 0 else 'down'} on {d[cross]}" if cross else "; no cross in the last 60 sessions")
             + f", and MACD is {'above' if macd[-1] > 0 else 'below'} zero.")

    # volatility
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(max(1, n - 14), n)]
    atr = sum(tr) / len(tr)
    mid = a20 or last
    sd = (sum((x - mid) ** 2 for x in c[-20:]) / 20) ** 0.5
    if sd:
        pb = (last - (mid - 2 * sd)) / (4 * sd)
        bw = [(lambda m, s: 4 * s / m if m else 0)(sum(c[i - 19:i + 1]) / 20, (sum((x - sum(c[i - 19:i + 1]) / 20) ** 2 for x in c[i - 19:i + 1]) / 20) ** 0.5)
              for i in range(max(19, n - 126), n)]
        rank = sum(1 for x in bw if x <= bw[-1]) / len(bw)
        L.append(f"Volatility: average true range ${atr:,.2f} a day ({atr / last * 100:.1f}% of price). Bollinger bands (20-day, 2 standard deviations) "
                 f"${mid - 2 * sd:,.2f} to ${mid + 2 * sd:,.2f}; price sits at {pb * 100:.0f}% of the band. Band width is narrower than "
                 f"{(1 - rank) * 100:.0f}% of the last 6 months" + (" (a squeeze: quiet stretches often end in a bigger move)." if rank <= 0.1 else "."))

    # volume
    v50 = sum(v[-50:]) / 50 if n >= 50 else None
    if v50:
        upv = sum(v[i] for i in range(n - 20, n) if c[i] > c[i - 1])
        dnv = sum(v[i] for i in range(n - 20, n) if c[i] < c[i - 1])
        big = max(range(n - 20, n), key=lambda i: v[i])
        L.append(f"Volume: last session {v[-1] / v50:.1f}× its 50-day average ({v50 / 1e6:.1f}M shares). Over 20 sessions, up days traded "
                 f"{upv / dnv:.2f}× the volume of down days" + (" (buyers more active)" if upv > dnv * 1.2 else " (sellers more active)" if dnv > upv * 1.2 else "") +
                 f". Heaviest day: {d[big]}, {v[big] / v50:.1f}× average, {_pct(c[big] / c[big - 1] - 1)}." if dnv else "")

    # levels
    yr = range(max(0, n - 252), n)
    hi_i, lo_i = max(yr, key=lambda i: h[i]), min(yr, key=lambda i: l[i])
    L.append(f"52-week high ${h[hi_i]:,.2f} on {d[hi_i]} ({_pct(last / h[hi_i] - 1)} from it, {n - 1 - hi_i} sessions ago); "
             f"low ${l[lo_i]:,.2f} on {d[lo_i]} ({_pct(last / l[lo_i] - 1)} above it).")
    lv = _levels(h, l, c, d)
    below = sorted([x for x in lv if x[0] < last * 0.995], key=lambda x: -x[0])[:3]
    above = sorted([x for x in lv if x[0] > last * 1.005], key=lambda x: x[0])[:3]
    rows = [["Resistance", f"${p:,.2f}", _pct(p / last - 1), k, day] for p, k, day in reversed(above)] + \
           [["Support", f"${p:,.2f}", _pct(p / last - 1), k, day] for p, k, day in below]
    if rows:
        L += ["", "Levels from swing highs and lows over 6 months (more touches, stronger level):",
              _table(["Kind", "Price", "From here", "Touches", "Last touch"], rows)]

    # relative strength against the market and the sector
    def ret(cs, k):
        return cs[-1] / cs[-1 - k] - 1 if len(cs) > k and cs[-1 - k] else None
    peers = [("SPY", "S&P 500")] + ([(_sector_etf(info), "sector")] if _sector_etf(info) else [])
    rows = []
    for t, lab in peers:
        try:
            pc = srv.extra("ohlc", {"t": [t]})["c"]
        except Exception:
            continue
        rows.append([f"{sym} vs {t} ({lab})"] + [_pct(ret(c, k) - ret(pc, k)) if ret(c, k) is not None and ret(pc, k) is not None else "n/a" for k in (21, 63, 126, 252)])
    if rows:
        L += ["", "Relative strength (return difference, positive means outperforming):", _table(["", "1M", "3M", "6M", "1Y"], rows)]

    # the last ten sessions
    rows = [[d[i], f"${c[i]:,.2f}", _pct(c[i] / c[i - 1] - 1), f"{v[i] / v50:.1f}×" if v50 else "n/a"] for i in range(n - 1, n - 11, -1)]
    L += ["", "Last 10 sessions:", _table(["Date", "Close", "Change", "Volume vs 50-day"], rows)]
    return L


# ---------------------------------------------------------------- insider trades in depth
WHAT = {"buy": "Open-market buy", "sell": "Sale", "exercise": "Option exercise", "award": "Stock award", "gift": "Gift", "other": "Other"}


def sec_insiders(o, price):
    if not o:
        return []
    tx = o.get("insiders") or []
    today = dt.date.today()

    def age(x):
        try:
            return (today - dt.date.fromisoformat(x["date"][:10])).days
        except Exception:
            return 9999
    for x in tx:
        x.setdefault("what", x.get("kind"))
    L = []
    m = o.get("major") or {}
    if m.get("insidersPercentHeld") is not None:
        L.append(f"Insiders own {m['insidersPercentHeld'] * 100:.2f}% of the shares.")
    for n in (90, 365):
        win = [x for x in tx if age(x) <= n]
        b = [x for x in win if x["what"] == "buy"]
        s = [x for x in win if x["what"] == "sell"]
        def part(xs, word):
            if not xs:
                return f"no {word}s"
            return f"{_n(len(xs), word)} by {_n(len({x['insider'] for x in xs}), 'person', 'people')} ({_money(sum(x.get('value') or 0 for x in xs))})"
        L.append(f"Last {n} days: {part(b, 'open-market buy')}; {part(s, 'sale')}; "
                 f"{_n(sum(1 for x in win if x['what'] == 'exercise'), 'option exercise')}, {_n(sum(1 for x in win if x['what'] == 'award'), 'stock award')}, "
                 f"{_n(sum(1 for x in win if x['what'] == 'gift'), 'gift')}.")
    # cluster buying: several different insiders buying within 30 days is the strongest signal in this data
    buys = sorted((x for x in tx if x["what"] == "buy"), key=lambda x: x["date"])
    clusters = []
    for i, x in enumerate(buys):
        d0 = dt.date.fromisoformat(x["date"][:10])
        grp = [y for y in buys[i:] if (dt.date.fromisoformat(y["date"][:10]) - d0).days <= 30]
        who = {y["insider"] for y in grp}
        if len(who) >= 2 and not any(set(who) <= c["who"] for c in clusters):
            clusters.append({"start": x["date"], "end": grp[-1]["date"], "who": who, "value": sum(y.get("value") or 0 for y in grp)})
    L.append("Cluster buying (2+ insiders buying within 30 days): " + ("; ".join(
        f"{len(c['who'])} insiders from {c['start']} to {c['end']}, {_money(c['value'])}" for c in clusters) if clusters else "none in the last year") + ".")

    # who is trading, against what they still hold
    def key(name):
        return re.sub(r"[^A-Z]", "", str(name or "").upper())
    held = {key(r.get("name")): (r.get("direct") or 0) + (r.get("indirect") or 0) for r in o.get("roster") or []}
    people = {}
    for x in tx:
        if x["what"] not in ("buy", "sell"):
            continue
        p = people.setdefault(x["insider"], {"role": x.get("role") or "", "b": 0, "s": 0, "bs": 0, "ss": 0, "n": 0, "last": x["date"]})
        p["n"] += 1
        p["last"] = max(p["last"], x["date"])
        if x["what"] == "buy":
            p["b"] += x.get("value") or 0
            p["bs"] += x.get("shares") or 0
        else:
            p["s"] += x.get("value") or 0
            p["ss"] += x.get("shares") or 0
    rows = []
    for name, p in sorted(people.items(), key=lambda kv: -(kv[1]["b"] + kv[1]["s"]))[:10]:
        now = held.get(key(name))
        stake = f"{p['ss'] / (p['ss'] + now) * 100:.0f}%" if now and p["ss"] else ("0%" if now else "n/a")
        rows.append([str(name).title(), p["role"], _money(p["b"]) if p["b"] else "", _money(p["s"]) if p["s"] else "", p["n"], p["last"],
                     f"{now / 1e6:.2f}M" if now and now >= 1e6 else f"{now:,.0f}" if now else "n/a", stake])
    if rows:
        L += ["", "By insider, last 12 months (buys and sales only):",
              _table(["Insider", "Role", "Bought", "Sold", "Trades", "Last", "Shares held now", "Sold as % of stake"], rows)]
    rows = [[x["date"], str(x.get("insider") or "").title(), x.get("role") or "", WHAT.get(x["what"], x["what"]),
             f"{x['shares']:,.0f}" if x.get("shares") else "", f"${x['price']:,.2f}" if x.get("price") else "",
             _money(x.get("value")) if x.get("value") else "", _pct(price / x["price"] - 1) if price and x.get("price") else ""]
            for x in tx if x["what"] in ("buy", "sell", "exercise")][:15]
    if rows:
        L += ["", "Recent trades:", _table(["Date", "Insider", "Role", "Type", "Shares", "Price", "Value", "Price now vs then"], rows)]
    L.append("Notes: Yahoo doesn't say which sales were pre-planned (10b5-1 trading plans) or sold to cover taxes on vesting stock. "
             "Shares held now come from each insider's latest filing.")
    return L


def sec_options(op):
    if not op or not op.get("expirations"):
        return []
    L = []
    n = op.get("near") or {}
    if n.get("move"):
        L.append(f"Nearest expiry {n['expiry']} ({n['days']} days): options price a ±{n['move'] * 100:.1f}% move; at-the-money implied volatility {_pct(n.get('iv'), 0, False)}.")
    if op.get("pcVolume") is not None:
        L.append(f"Put/call ratio: {op['pcVolume']:.2f} by volume, {op.get('pcOI') or 0:.2f} by open interest (above 1 leans defensive).")
    u = op.get("unusual") or []
    if u:
        L.append("Unusual activity (volume well above open interest): " + "; ".join(
            f"${x['strike']:g} {x['side']} {x['expiry']} {x['volume']:,} traded vs {x['oi']:,} open" for x in u[:5]) + ".")
    return L


def sec_news(news):
    rows = []
    for n in (news or [])[:8]:
        d = dt.datetime.fromtimestamp(n["time"], srv.NY).strftime("%b %-d") if n.get("time") else ""
        rows.append(f"- {d} · {n.get('publisher') or ''}: {n['title']}" + (f" ({n['summary'][:180]})" if n.get("summary") else ""))
    return rows


def sec_financials(fi):
    if not fi:
        return []
    L = []
    for freq in ("quarterly", "annual"):
        b = (fi.get(freq) or {}).get("income") or {}
        if not b.get("periods"):
            continue
        per = b["periods"][-5:]
        rows = []
        for r in b["rows"]:
            vals = r["values"][-5:]
            rows.append([r["label"]] + [(_money(v) if abs(v or 0) > 1000 else f"{v:.2f}") if v is not None else "n/a" for v in vals])
        L += [f"{freq.title()} income statement:", _table(["Line"] + [p[:7] for p in per], rows), ""]
        cf = (fi.get(freq) or {}).get("cashflow") or {}
        rows = [[r["label"]] + [_money(v) if v is not None else "n/a" for v in r["values"][-5:]] for r in cf.get("rows") or []]
        if rows:
            L += [f"{freq.title()} cash flow:", _table(["Line"] + [p[:7] for p in cf["periods"][-5:]], rows), ""]
    return L


def sec_events(ev):
    if not ev:
        return []
    L = []
    dy = ev.get("dividendYears") or []
    if dy:
        L.append("Dividends per share by year: " + ", ".join(f"{d['year']} ${d['total']:.2f}" for d in dy[-6:]) + ".")
    sp = ev.get("splits") or []
    if sp:
        L.append("Splits: " + ", ".join(f"{s['date']} {s['ratio']}:1" for s in sp[-4:]) + ".")
    fl = ev.get("filings") or []
    if fl:
        L.append("Recent filings: " + "; ".join(f"{f['date']} {f['type']} {f.get('title') or ''}".strip() for f in fl[:8]) + ".")
    return L


def _my_position(sym, uid):
    snap = srv.personal.snapshot(uid)
    L = []
    ps = [p for p in snap["positions"] if p["t"] == sym]
    _, arr = _series(sym)
    last = arr[-1] if arr else None
    if ps and last:
        sh = sum(p["shares"] for p in ps)
        cost = sum(p["shares"] * p["cost"] for p in ps)
        L.append(f"You own {sh:g} shares, average cost ${cost / sh:,.2f}, now worth {_money(sh * last)} ({_pct(sh * last / cost - 1)} total gain).")
    elif sym in snap["watch"]:
        L.append("It's on your watchlist; you don't own it.")
    return L


SECTIONS = {
    "analysts": ("Analysts", ["analysts", "detail"]),
    "earnings": ("Earnings", ["earnhist", "options"]),
    "ownership": ("Ownership and insiders", ["ownership"]),
    "options": ("Options", ["options"]),
    "news": ("News", ["detail"]),
    "financials": ("Financials", ["financials"]),
    "events": ("Dividends, splits and filings", ["events"]),
    "insiders": ("Insider trades", ["ownership"]),
    "technicals": ("Technicals", ["ohlc"]),
}


def stock_context(sym, uid=None, only=None, timeout=25):
    sym = srv.yahoo_symbol(sym)
    if not srv.VALID.fullmatch(sym):
        raise ValueError("That isn't a ticker symbol.")
    if sym not in srv.S.px:
        srv.S.track(sym)
    names = sorted({n for k in (only or ["analysts", "earnings", "ownership", "options", "news"]) for n in SECTIONS[k][1]} | {"detail"})
    got = gather(sym, names, timeout)
    d = got.get("detail") or {}
    info = d.get("info") or {}
    _, arr = _series(sym)
    price = arr[-1] if arr else info.get("currentPrice")
    title = info.get("longName") or info.get("shortName") or sym
    L = [f"# {sym}" + (f": {title}" if title != sym else ""), f"Data as of {_now_ny()}. Source: Yahoo Finance via {APP_NAME}.", ""]
    if not only:
        mem = fund_membership(sym)
        if mem:
            L.append("Weight in the funds this app tracks: " + ", ".join(mem) + ".")
        if uid:
            L += _my_position(sym, uid)
        L += ["", "## Company"] + (sec_company(info) or ["(Yahoo didn't return the company profile just now.)"])
        L += ["", "## Price and trend"] + price_lines(sym)
    for k in (only or ["analysts", "earnings", "ownership", "options", "news"]):
        body = {"analysts": lambda: sec_analysts(got.get("analysts"), info, price),
                "earnings": lambda: sec_earnings(sym, got.get("earnhist"), got.get("options")),
                "ownership": lambda: sec_ownership(got.get("ownership")),
                "options": lambda: sec_options(got.get("options")),
                "news": lambda: sec_news(d.get("news")),
                "financials": lambda: sec_financials(got.get("financials")),
                "events": lambda: sec_events(got.get("events")),
                "insiders": lambda: sec_insiders(got.get("ownership"), price),
                "technicals": lambda: sec_technicals(sym, got.get("ohlc"), info)}[k]()
        missing = [n for n in SECTIONS[k][1] if n not in got]
        L += ["", f"## {SECTIONS[k][0]}"] + (body or [f"(Yahoo didn't return this just now{': ' + ', '.join(missing) if missing else ''}.)"])
        old = [a for a in (srv.stale_age(_cache_key(n, sym)) for n in SECTIONS[k][1]) if a]
        if body and old:
            L.append(f"(Yahoo didn't refresh this just now, so it's the copy from {srv._ago(max(old))}.)")
    return "\n".join(L).strip() + "\n"


def portfolio_context(uid):
    snap = srv.personal.snapshot(uid)
    L = [f"# Your stocks", f"Data as of {_now_ny()}.", ""]
    pos = {}
    for p in snap["positions"]:
        q = pos.setdefault(p["t"], {"sh": 0.0, "cost": 0.0})
        q["sh"] += p["shares"]
        q["cost"] += p["shares"] * p["cost"]
    rows, total, day, cost_all = [], 0.0, 0.0, 0.0
    vals = {}
    for t, q in pos.items():
        _, arr = _series(t)
        if not arr or arr[-1] is None:
            continue
        v = q["sh"] * arr[-1]
        vals[t] = v
        total += v
        cost_all += q["cost"]
        r1 = _ret(arr, 1)
        day += v - v / (1 + r1) if r1 is not None else 0
    if vals:
        for t, v in sorted(vals.items(), key=lambda kv: -kv[1]):
            _, arr = _series(t)
            q = pos[t]
            rows.append([t, f"{q['sh']:g}", f"${q['cost'] / q['sh']:,.2f}", f"${arr[-1]:,.2f}", _money(v), _pct(v / total, 1, False),
                         _pct(_ret(arr, 1)), _pct(_ret(arr, 21)), _pct(v / q["cost"] - 1)])
        L += ["## Portfolio", f"Value {_money(total)}, today {'+' if day >= 0 else '-'}{_money(abs(day))}, total gain {_pct(total / cost_all - 1)} on {_money(cost_all)} cost.", "",
              _table(["Ticker", "Shares", "Avg cost", "Price", "Value", "Weight", "1D", "1M", "Total gain"], rows)]
        with srv.S.lock:
            ext = srv.S.ext_view()
        moves = [(t, ext[t]) for t in vals if t in ext]
        if moves:
            lab = "Pre-market" if moves[0][1][2] == "pre" else "After hours"
            xd = sum(pos[t]["sh"] * (x[0] - vals[t] / pos[t]["sh"]) for t, x in moves)
            L += ["", f"{lab} (thin trading, from the last close): portfolio {'+' if xd >= 0 else '-'}{_money(abs(xd))}; "
                  + ", ".join(f"{t} ${x[0]:,.2f} {_pct(x[3])}" for t, x in sorted(moves, key=lambda m: -abs(m[1][3]))) + "."]
        sec = {}
        for t, v in vals.items():
            s = (srv.S.sectors.get(t) or {}).get("sector") if isinstance(srv.S.sectors.get(t), dict) else srv.S.sectors.get(t)
            sec[s or "Other"] = sec.get(s or "Other", 0) + v / total
        L += ["", "Sector mix: " + ", ".join(f"{k} {_pct(v, 0, False)}" for k, v in sorted(sec.items(), key=lambda kv: -kv[1])) + "."]
    else:
        L += ["No positions recorded yet."]
    if snap["watch"]:
        rows = []
        for t in snap["watch"]:
            d, arr = _series(t)
            if arr and arr[-1] is not None:
                rows.append([t, f"${arr[-1]:,.2f}", _pct(_ret(arr, 1)), _pct(_ret(arr, 21)), _pct(_ytd(d, arr))])
        L += ["", "## Watchlist", _table(["Ticker", "Price", "1D", "1M", "YTD"], rows)]
    syms = sorted(set(pos) | set(snap["watch"]))
    up = [(t, srv.EARN[t]) for t in syms if t in srv.EARN and srv.EARN[t].get("date", "") >= dt.date.today().isoformat() and srv.EARN[t].get("reported") is None]
    if up:
        L += ["", "Upcoming earnings: " + "; ".join(f"{t} {e['date']} {e.get('timing') or ''}".strip() for t, e in sorted(up, key=lambda x: x[1]["date"])) + "."]
    b = srv.brief(uid)
    if b["items"]:
        L += ["", "## Brief (research changes in the last two weeks)"]
        for it in sorted(b["items"], key=lambda x: -x.get("score", 0))[:14]:
            L.append(f"- {it['t']} · {it['date']}: {it['head']}{' ' + it['text'] if it.get('text') else ''}")
    return "\n".join(L).strip() + "\n"


def contributions(weights, rets):
    """Each holding's contribution to a fund's return, the same way the Funds page computes it.
    Issuers publish today's weights; a holding's weight at the start of the period is today's weight divided by
    (1 + its return), rescaled so the weights still add up. Contribution = start weight × return, so the
    contributions add up to the basket's return. Holdings without a return keep their weight and contribute 0.
    weights are fractions (0.07 for 7%); returns are fractions; returns (start weight, contribution) pairs."""
    raw = [w if r is None else w / (1 + r) for w, r in zip(weights, rets)]
    scale = sum(weights) / sum(raw) if sum(raw) else 0
    out = []
    for w0, r in zip(raw, rets):
        w0 *= scale
        out.append((w0, 0.0 if r is None else w0 * r))
    return out


def _contrib(fund, n):
    hs = (srv.S.holdings.get(fund) or {}).get("holdings", [])
    rets = [_ret(_series(h["t"])[1], n) for h in hs]
    out = []
    for h, r, (w0, c) in zip(hs, rets, contributions([h["w"] / 100 for h in hs], rets)):
        if r is not None:
            out.append((h["t"], h["n"], w0, r, c))
    return out


def fund_context(fund, n=1):
    fund = fund.upper()
    if fund not in srv.FUNDS:
        raise ValueError(f"{fund} isn't one of the tracked funds: {', '.join(srv.FUNDS)}.")
    lab = next((k for k, v in HORIZONS if v == n), f"{n} sessions")
    _, arr = _series(fund)
    c = _contrib(fund, n)
    L = [f"# {fund}: {srv.FUNDS[fund]}, {lab}", f"Data as of {_now_ny()}.", f"Fund return {_pct(_ret(arr, n))}."]
    if c:
        up = sum(1 for x in c if x[3] > 0)
        eq = sum(x[3] for x in c) / len(c)
        L.append(f"{up} of {len(c)} holdings up; the average holding returned {_pct(eq)} (equal weight).")
        top = sorted(c, key=lambda x: -x[4])
        fmt = lambda xs: _table(["Ticker", "Name", "Start weight", "Return", "Contribution"], [[x[0], x[1], _pct(x[2], 2, False), _pct(x[3]), f"{x[4] * 1e4:+.0f} bp"] for x in xs])
        L += ["", "Biggest lifts:", fmt(top[:8]), "", "Biggest drags:", fmt(top[::-1][:8])]
    return "\n".join(L) + "\n"


def market_context():
    L = [f"# Market", f"Data as of {_now_ny()}.", ""]
    rows = []
    for f in srv.FUNDS:
        d, arr = _series(f)
        rows.append([f, srv.FUNDS[f], _pct(_ret(arr, 1)), _pct(_ret(arr, 5)), _pct(_ret(arr, 21)), _pct(_ytd(d, arr))])
    L += [_table(["Fund", "Name", "1D", "1W", "1M", "YTD"], rows)]
    try:
        m = srv.extra("macro", {})
        dates, px = m["daily"]["dates"], m["daily"]["px"]
        rows = []
        for sym, (name, kind) in m["names"].items():
            a = _trim(px.get(sym) or [])
            if a:
                last = a[-1]
                if kind == "rate":
                    ch = lambda n: f"{(last - a[-1 - n]):+.2f} pts" if len(a) > n and a[-1 - n] else "n/a"
                    rows.append([name, f"{last:.2f}%", ch(1), ch(21)])
                else:
                    rows.append([name, f"{last:,.2f}", _pct(_ret(a, 1)), _pct(_ret(a, 21))])
        L += ["", "## Macro", _table(["Market", "Level", "1D", "1M"], rows)]
        rows = []
        for sym, name, _k in m.get("sectors") or []:
            a = _trim(px.get(sym) or [])
            if a:
                rows.append([name, sym, _pct(_ret(a, 1)), _pct(_ret(a, 5)), _pct(_ret(a, 21)), _pct(_ret(a, 63))])
        if rows:
            rows.sort(key=lambda r: -float(r[4].rstrip("%")) if r[4] != "n/a" else 0)
            L += ["", "## Sectors (SPDR sector funds, sorted by 1M)", _table(["Sector", "Fund", "1D", "1W", "1M", "3M"], rows)]
        ov = m.get("overnight") or {}
        if ov.get("q"):
            rows = [[ov["names"].get(sym, sym) + " futures", f"{f['last']:,.2f}", _pct(f["chg"])] for sym, f in ov["q"].items()]
            L += ["", f"## Index futures since the stock close ({ov['since'][:16].replace('T', ' ')} New York)"
                  + ("" if ov.get("trading") else ", paused now, last trades"),
                  "Stocks are closed; futures trade overnight and are the best read on the next open.",
                  _table(["Future", "Price", "Since close"], rows)]
        st = m.get("status") or {}
        if st.get("message"):
            L.append(f"Status: {st['message']}.")
    except Exception:
        pass
    c = sorted(_contrib("SPY", 1), key=lambda x: -x[4])
    if c:
        L += ["", "S&P 500 today, biggest lifts: " + ", ".join(f"{x[0]} {_pct(x[3])}" for x in c[:6]) + ".",
              "Biggest drags: " + ", ".join(f"{x[0]} {_pct(x[3])}" for x in c[::-1][:6]) + "."]
    return "\n".join(L) + "\n"


def brief_text(uid):
    b = srv.brief(uid)
    if not b["items"]:
        return "No research changes for your stocks right now." + (" (Still gathering data; try again in a minute.)" if b["pending"] else "") + "\n"
    L = [f"# Brief for your {b['count']} stocks", ""]
    for it in sorted(b["items"], key=lambda x: -x.get("score", 0)):
        L.append(f"- {it['t']} · {it['date']}: {it['head']}{' ' + it['text'] if it.get('text') else ''}")
    return "\n".join(L) + "\n"


def compare_context(syms):
    syms = [srv.yahoo_symbol(s) for s in syms][:6]
    for s in syms:
        if s not in srv.S.px:
            srv.S.track(s)
    rows = []
    for s in syms:
        d, arr = _series(s)
        info = (srv.stock_detail(s) or {}).get("info") or {}
        rows.append([s, _pct(_ret(arr, 1)), _pct(_ret(arr, 21)), _pct(_ytd(d, arr)), _pct(_ret(arr, 252)),
                     _money(info.get("marketCap")), _num(info.get("forwardPE"), 1, "×"), _pct(info.get("revenueGrowth")),
                     _pct(info.get("operatingMargins"), 0, False), (info.get("recommendationKey") or "").replace("_", " ")])
    return "# Comparison\n" + _table(["Ticker", "1D", "1M", "YTD", "1Y", "Mkt cap", "Fwd P/E", "Rev growth", "Op margin", "Analysts"], rows) + "\n"


def history_context(syms, n, label):
    """Daily closes for up to five tickers, thinned to about 40 rows, plus each one's change since the first row."""
    syms = [srv.yahoo_symbol(s) for s in syms if s][:5]
    if not syms:
        raise ValueError("usage: openticker history TICKER [TICKER ...] --h 3M")
    for s in syms:
        if s not in srv.S.px:
            srv.S.track(s)
    with srv.S.lock:
        dates = list(srv.S.dates)
        px = {s: list(srv.S.px.get(s) or []) for s in syms}
    syms = [s for s in syms if any(v for v in px[s])]
    if not syms or not dates:
        return "No price history for those tickers.\n"
    k = min(n + 1, len(dates))
    dates = dates[-k:]
    px = {s: px[s][-k:] for s in syms}
    step = max(1, -(-len(dates) // 40))
    idx = sorted(set([0] + list(range(len(dates) - 1, -1, -step))))
    first = {s: next((v for v in px[s] if v), None) for s in syms}
    rows = []
    for i in idx:
        r = [dates[i]]
        r += [f"{px[s][i]:.2f}" if px[s][i] else "" for s in syms]
        r += [f"{(px[s][i] / first[s] - 1) * 100:+.1f}" if px[s][i] and first[s] else "" for s in syms]
        rows.append(r)
    head = ["Date"] + [f"{s} close" for s in syms] + [f"{s} % since {dates[0]}" for s in syms]
    return (f"# Daily closes, last {label}\n\n" + (f"Every {step} trading days. " if step > 1 else "Every trading day. ") +
            "To compare stocks on one chart, use the % columns.\n\n" + _table(head, rows) + "\n")


def calendar_context(uid):
    syms = srv._user_syms(uid) if uid else set()
    today = dt.date.today().isoformat()
    end = (dt.date.today() + dt.timedelta(days=14)).isoformat()
    big = []
    for t, e in srv.EARN.items():
        if today <= e.get("date", "") <= end and e.get("reported") is None:
            w = sum(h["w"] for f in srv.FUNDS for h in (srv.S.holdings.get(f) or {}).get("holdings", []) if h["t"] == t and f == "SPY")
            big.append((t, e, w))
    mine = [x for x in big if x[0] in syms]
    big = sorted([x for x in big if x[2] >= 0.4], key=lambda x: x[1]["date"])
    L = ["# Next two weeks", ""]
    if mine:
        L.append("Your stocks reporting: " + "; ".join(f"{t} {e['date']} {e.get('timing') or ''}".strip() for t, e, _ in sorted(mine, key=lambda x: x[1]["date"])) + ".")
    if big:
        L.append("Largest S&P 500 companies reporting: " + "; ".join(f"{t} {e['date']}" for t, e, _ in big[:20]) + ".")
    try:
        ec = srv.extra("econ", {})
        rows = [r for r in (ec if isinstance(ec, list) else ec.get("rows") or [])][:20]
        if rows:
            L += ["", "Economic calendar:"] + [f"- {json.dumps(r, default=str)}" for r in rows]
    except Exception:
        pass
    return "\n".join(L) + "\n"


def prices_json(syms, n):
    """Daily closes for up to ten tickers as JSON, for `openticker calc` (which loads them into pandas)."""
    syms = list(dict.fromkeys(srv.yahoo_symbol(s) for s in syms if s))[:10]
    for s in syms:
        if s not in srv.S.px:
            srv.S.track(s)
    with srv.S.lock:
        dates = list(srv.S.dates)
        px = {s: list(srv.S.px.get(s) or []) for s in syms}
    k = min(n, len(dates))
    return json.dumps({"dates": dates[-k:] if k else [],
                       "px": {s: [v if v else None for v in px[s][-k:]] for s in syms if any(px[s])},
                       "missing": [s for s in syms if not any(px[s])]})


def text_for(cmd, args, uid):
    """Dispatch for /api/agent/<cmd> and the openticker CLI."""
    t = (args.get("t") or [""])[0]
    if cmd == "stock":
        return stock_context(t, uid)
    if cmd in SECTIONS:
        return stock_context(t, uid, only=[cmd])
    if cmd == "portfolio":
        return portfolio_context(uid)
    if cmd == "brief":
        return brief_text(uid)
    if cmd == "market":
        return market_context()
    if cmd == "fund":
        n = dict(HORIZONS).get((args.get("h") or ["1D"])[0].upper(), 1)
        return fund_context(t or "SPY", n)
    if cmd == "compare":
        return compare_context([s for s in re.split(r"[,\s]+", (args.get("t") or [""])[0]) if s])
    if cmd == "calendar":
        return calendar_context(uid)
    if cmd == "history":
        h = (args.get("h") or ["3M"])[0].upper()
        return history_context([x for x in re.split(r"[,\s]+", t) if x], dict(HORIZONS).get(h, 63), h)
    if cmd == "prices":
        h = (args.get("h") or ["ALL"])[0].upper()
        return prices_json([x for x in re.split(r"[,\s]+", t) if x], dict(HORIZONS).get(h, 100000) + 1)
    if cmd == "search":
        res = srv.search_tickers((args.get("q") or [""])[0][:40])
        return "\n".join(f"- {r.get('t')}: {r.get('n') or ''}" + "".join(f" ({x})" for x in [", ".join(v for v in (r.get('type', '').title().replace('Etf', 'ETF').replace('Equity', 'Stock'), r.get('exch')) if v)] if x)
                         for r in res) + "\n" if res else "No matches.\n"
    if cmd == "skills":
        return "\n".join(f"- {s['name']}: {s['description']}" for s in skills()) + "\n"
    raise ValueError(f"Unknown command {cmd}.")


# ---------------------------------------------------------------- skills
def _parse_skill(path: Path):
    raw = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return None
    meta, body = {}, m.group(2).strip()
    cur = meta
    for line in m.group(1).splitlines():
        if re.match(r"^\S[^:]*:\s*$", line):          # nested map like "metadata:"
            cur = meta.setdefault(line.split(":")[0].strip(), {})
            continue
        mm = re.match(r"^(\s*)([A-Za-z_-]+):\s*(.*)$", line)
        if mm:
            (cur if mm.group(1) else meta)[mm.group(2)] = mm.group(3).strip().strip('"')
            if not mm.group(1):
                cur = meta
    md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    return {"name": meta.get("name") or path.parent.name, "description": meta.get("description", ""),
            "label": md.get("label") or meta.get("name"), "scope": md.get("scope", "any"),
            "prompt": md.get("prompt", ""), "blurb": md.get("blurb", ""), "order": int(md.get("order") or 9), "hidden": md.get("hidden") == "true", "body": body}


def skills():
    out = []
    for p in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        try:
            s = _parse_skill(p)
            if s and not s["hidden"]:
                out.append(s)
        except Exception:
            pass
    order = {"stock": 0, "portfolio": 1, "market": 2, "any": 3}
    return sorted(out, key=lambda s: (order.get(s["scope"], 9), s["order"], s["name"]))


def skill(name):
    return next((s for s in skills() if s["name"] == name), None)


# ---------------------------------------------------------------- providers (the user's own agents)
SEARCH_PATHS = ["~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.opencode/bin", "~/.npm-global/bin",
                "~/.bun/bin", "~/.volta/bin", "~/.claude/local", "/usr/bin"]


def _which(name):
    path = os.pathsep.join([os.environ.get("PATH", ""), login_path()] + [os.path.expanduser(p) for p in SEARCH_PATHS])
    return shutil.which(name, path=path)


PROVIDERS = [
    {"id": "claude", "label": "Claude Code", "bin": "claude", "note": "Bills your Claude plan", "tools": True,
     "install": "curl -fsSL https://claude.ai/install.sh | bash", "login": "claude auth login", "site": "https://claude.com/claude-code"},
    {"id": "codex", "label": "Codex", "bin": "codex", "note": "Bills your ChatGPT plan", "tools": True,
     "install": "curl -fsSL https://chatgpt.com/codex/install.sh | sh", "login": "codex login", "site": "https://developers.openai.com/codex"},
    {"id": "opencode", "label": "OpenCode", "bin": "opencode", "note": "Free models, or your own providers", "tools": True,
     "install": "curl -fsSL https://opencode.ai/v2/install | bash", "login": "opencode providers login", "site": "https://opencode.ai"},
    {"id": "ollama", "label": "Ollama", "bin": "ollama", "note": "Free and private, runs on this Mac", "tools": False,
     "install": "brew install ollama && ollama pull llama3.2", "login": "ollama pull llama3.2", "site": "https://ollama.com"},
]
_prov_cache = {"t": 0, "v": None}
NOT_CHAT = re.compile(r"ocr|embed|vision-only|whisper|rerank", re.I)


def _ollama_models():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as r:
            return [m["name"] for m in json.load(r).get("models", []) if not NOT_CHAT.search(m["name"])]
    except Exception:
        return None


def _signed_in(pid, path):
    """True / False when the agent can tell us, None when it can't."""
    try:
        if pid == "claude":
            r = subprocess.run([path, "auth", "status"], capture_output=True, text=True, timeout=8, env=_env("claude"))
            return bool(json.loads(r.stdout or "{}").get("loggedIn"))
        if pid == "codex":
            r = subprocess.run([path, "login", "status"], capture_output=True, text=True, timeout=8, env=_env("codex"))
            return r.returncode == 0 and "logged in" in (r.stdout + r.stderr).lower() and "not logged in" not in (r.stdout + r.stderr).lower()
    except Exception:
        return None
    return True


SEEN_FILE = paths.DATA / "agent-models.json"
CLAUDE_MODELS = [["", "Default"], ["opus", "Opus"], ["sonnet", "Sonnet"], ["haiku", "Haiku"]]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]   # how hard the model thinks; Claude Code and Codex both take these


def _seen():
    try:
        return json.loads(SEEN_FILE.read_text())
    except Exception:
        return {}


def remember_model(pid, asked, model):
    """The model an agent actually answered with, so the picker can name it before the next answer."""
    if not model:
        return
    s = _seen()
    key = f"{pid}:{asked or ''}"
    if s.get(key) != model:
        s[key] = model
        try:
            SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            SEEN_FILE.write_text(json.dumps(s))
        except OSError:
            pass


def _configured_model(pid):
    """The default model in the agent's own settings, when it names one."""
    try:
        if pid == "claude":
            for f in (Path.home() / ".claude" / "settings.json", Path.home() / ".claude" / "settings.local.json"):
                if f.exists():
                    m = json.loads(f.read_text() or "{}").get("model")
                    if m:
                        return m
        elif pid == "codex":
            f = Path.home() / ".codex" / "config.toml"
            if f.exists():
                m = re.search(r'^\s*model\s*=\s*"([^"]+)"', f.read_text(), re.M)
                if m:
                    return m.group(1)
        elif pid == "opencode":
            return _opencode_model()
    except Exception:
        return None
    return None


def _configured_effort(pid):
    """The effort level in the agent's own settings, when it sets one."""
    try:
        if pid == "claude":
            for f in (Path.home() / ".claude" / "settings.local.json", Path.home() / ".claude" / "settings.json"):
                if f.exists():
                    e = json.loads(f.read_text() or "{}").get("effortLevel")
                    if e:
                        return e
        elif pid == "codex":
            f = Path.home() / ".codex" / "config.toml"
            if f.exists():
                m = re.search(r'^\s*model_reasoning_effort\s*=\s*"([^"]+)"', f.read_text(), re.M)
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


def providers(force=False):
    """Every agent with its state: ready, signin (installed, not signed in), off (Ollama not running), missing."""
    if not force and time.time() - _prov_cache["t"] < 90 and _prov_cache["v"]:
        return _with_seen(_prov_cache["v"])
    out = []
    for p in PROVIDERS:
        q = {k: v for k, v in p.items() if k != "bin"}
        path = _which(p["bin"])
        if p["id"] == "ollama":
            models = _ollama_models()
            q["models"] = models or []
            q["state"] = "ready" if models else "off" if path and models is None else "signin" if path else "missing"
            q["why"] = {"off": "Installed but not running. Open the Ollama app.", "signin": "No models yet.", "missing": "Not installed."}.get(q["state"], "")
        elif not path:
            q["state"], q["why"] = "missing", "Not installed."
        else:
            ok = _signed_in(p["id"], path)
            q["state"] = "signin" if ok is False else "ready"
            q["why"] = "Installed, not signed in." if ok is False else ""
        q["available"] = q["state"] == "ready"
        if p["id"] == "claude":
            q["choices"] = CLAUDE_MODELS
        elif p["id"] == "ollama":
            q["choices"] = [[m, m] for m in q["models"]]
        else:
            q["choices"] = [["", "Default"]]
        q["configured"] = _configured_model(p["id"])
        q["efforts"] = EFFORTS if p["id"] in ("claude", "codex") else []
        q["effort"] = _configured_effort(p["id"]) if q["efforts"] else None
        out.append(q)
    _prov_cache.update(t=time.time(), v=out)
    return _with_seen(out)


def _with_seen(out):
    seen = _seen()
    for q in out:
        q["seen"] = {k.split(":", 1)[1]: v for k, v in seen.items() if k.startswith(q["id"] + ":")}
    return out


def open_terminal(pid, action):
    """Run an agent's official install or sign-in command in a Terminal window the user can watch."""
    p = next((x for x in PROVIDERS if x["id"] == pid), None)
    cmd = p and p.get(action if action in ("install", "login") else "")
    if not cmd:
        raise ValueError("Unknown step.")
    _prov_cache["t"] = 0
    if shutil.which("osascript"):
        script = 'tell application "Terminal" to activate\ntell application "Terminal" to do script "%s"' % cmd.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", script])
        return True
    return False


APP_STEPS = {"update": "update", "phone-on": "start --lan", "phone-off": "start --local", "edit": "edit"}


def open_app_terminal(step):
    """Run one of OpenTicker's own commands (update, phone access on or off) in a Terminal window the user can watch."""
    if step not in APP_STEPS:
        raise ValueError("Unknown step.")
    cli = shutil.which("openticker") or str(Path.home() / ".local" / "bin" / "openticker")
    if shutil.which("osascript"):
        cmd = f"{cli} {APP_STEPS[step]}"
        script = 'tell application "Terminal" to activate\ntell application "Terminal" to do script "%s"' % cmd.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", script])
        return True
    return False


# ---------------------------------------------------------------- ask
AGENT_NAME = "Tick"
SYSTEM = f"""You are {AGENT_NAME}, the analyst who lives inside {APP_NAME}, the user's market dashboard. You sit next to whatever they're looking at and they talk to you like a sharp friend who reads the tape all day.
Your manner: calm, plain-spoken, a little dry. Numbers before adjectives. You never hype, never panic, and you say "I don't know" or "the data doesn't show that" when it's true. You notice things (an outlier, a mismatch between the story and the numbers) and point them out briefly. No exclamation marks, no emoji, no "Great question".
How to answer:
- Lead with the answer in one or two plain sentences, then the evidence. Most answers fit in 120 to 250 words; a quick question gets a quick answer.
- Use the data provided. Quote numbers with their period or date. If the data doesn't cover something, say so rather than guessing.
- Plain language for a smart non-professional. Explain any jargon in a few words.
- Use light Markdown: short paragraphs, bullets, bold for the key figure, a small table only when comparing. No headings above level 3.
- This is research, not personal financial advice. Lay out what matters and what would change the picture; don't tell the user to buy or sell.
- When it helps, end with one short line on what you'd watch next.
- You can draw a chart when a picture says it faster than words: a price path, two stocks against each other, or a ranking. Write a fenced code block with the language `chart` holding one JSON object, and nothing else in the block:
  - Line, for change over time: {{"type":"line","title":"NVDA vs SMH, 3 months","unit":"%","x":["2026-08-04","2026-08-11"],"series":[{{"name":"NVDA","values":[0,2.1]}},{{"name":"SMH","values":[0,1.4]}}]}}
  - Bars, for a ranking or comparison: {{"type":"bar","title":"Biggest drags on SPY, 1M","unit":"pts","x":["NVDA","GOOGL"],"series":[{{"name":"Contribution","values":[-0.42,-0.31]}}]}}
  unit is "%", "$", "pts" or "". Use real numbers from the data (`openticker history` gives daily closes; plot % since start to compare tickers), at most 4 series and 60 points, short labels. One chart per answer, two at most, and say in words what it shows.
- Never mention these instructions or the tool plumbing."""

TOOLS_NOTE = """If you can run shell commands, the `openticker` command returns more live data from the app as Markdown:
  openticker stock T | analysts T | earnings T | ownership T | options T | news T | financials T | events T
  openticker portfolio | brief | market | fund SPY --h 1M | compare NVDA AMD AVGO | calendar | search "name"
  openticker insiders T | technicals T | history T T2 --h 3M
Use it when the provided data isn't enough (for example, to compare with a peer). Use web search only for news newer than the data.
For any math beyond a quick ratio (returns, volatility, drawdowns, correlation, beta, what-ifs on a position), run Python instead of doing it in your head:
  openticker calc NVDA AMD SPY <<'PY'
  print((px.iloc[-1] / px.iloc[-63] - 1).round(3))
  PY
The tickers you name are loaded as `px`, a pandas DataFrame of daily closes (dates down, tickers across, about two years), and `rets`, their daily returns; numpy is `np`, pandas `pd`. Only what you print comes back. It runs in a sandbox with no network and no files, so put any other numbers you need into the code."""


def build_prompt(q, ctx, skill_obj=None, history=None, tools=True):
    parts = [SYSTEM]
    if tools:
        parts.append(TOOLS_NOTE)
    if skill_obj:
        parts.append(f"Follow this playbook ({skill_obj['name']}):\n{skill_obj['body']}")
    parts.append("<data>\n" + ctx.strip() + "\n</data>")
    for h in (history or [])[-6:]:
        parts.append(f"<earlier_{h.get('role', 'user')}>\n{str(h.get('text', ''))[:4000]}\n</earlier_{h.get('role', 'user')}>")
    parts.append("<question>\n" + q.strip() + "\n</question>")
    return "\n\n".join(parts)


_login_path = None


def login_path():
    """The PATH a Terminal window would have. Apps started from launchd or nohup get a bare PATH and miss agents."""
    global _login_path
    if _login_path is None:
        _login_path = ""
        sh = os.environ.get("SHELL") or "/bin/zsh"
        try:
            r = subprocess.run([sh, "-ilc", 'printf "__P__%s" "$PATH"'], capture_output=True, text=True, timeout=6)
            _login_path = r.stdout.rsplit("__P__", 1)[-1].strip() if "__P__" in r.stdout else ""
        except Exception:
            pass
    return _login_path


# Runs bill the plan the agent is signed in with: drop API keys the server's own environment may carry.
PLAN_ONLY = {"claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"), "codex": ("CODEX_API_KEY", "OPENAI_API_KEY")}


def _env(provider=None):
    e = dict(os.environ)
    e["PATH"] = os.pathsep.join([str(BIN_DIR), login_path()] + [os.path.expanduser(p) for p in SEARCH_PATHS] + [e.get("PATH", "")])
    e["OPENTICKER_URL"] = f"http://127.0.0.1:{getattr(srv, 'PORT', 8765)}"
    if os.environ.get("OPENTICKER_AGENT_BILLING", "plan") == "plan":
        for k in PLAN_ONLY.get(provider, ()):
            e.pop(k, None)
    if provider == "claude":
        e.update(CLAUDE_CODE_DISABLE_BACKGROUND_TASKS="1", CLAUDE_CODE_MCP_STARTUP_WAIT_MS="0")
    return e


def _describe_tool(name, inp):
    if name in ("Bash", "bash", "shell", "execute", "exec_command", "local_shell"):
        cmd = (inp or {}).get("command") or (inp or {}).get("cmd") or ""
        cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        m = re.search(r"\bopenticker\s+(\w+)\s*([A-Za-z.\-^=, ]*)", cmd)
        if m and m.group(1) == "calc":
            ts = [x for x in re.split(r"[,\s]+", re.split(r"\s-", " " + m.group(2))[0].upper()) if x]
            return "Running the numbers" + (f" for {', '.join(ts[:4])}" if ts else "")
        if m:
            what = {"stock": "the full picture", "analysts": "analyst data", "earnings": "earnings history", "ownership": "insider and holder data",
                    "options": "options activity", "news": "the news", "financials": "the financial statements", "events": "dividends and filings",
                    "portfolio": "your portfolio", "brief": "your brief", "market": "the market", "fund": "fund drivers",
                    "compare": "a comparison", "calendar": "the calendar", "search": "a ticker",
                    "insiders": "insider trades", "technicals": "the chart", "history": "price history"}.get(m.group(1), m.group(1))
            return f"Checking {what}" + (f" for {m.group(2).strip().upper()}" if m.group(2).strip() and m.group(1) not in ("search", "fund") else "")
        return "Running a command"
    if name in ("WebSearch", "web_search"):
        return "Searching the web" + (f": {inp.get('query')}" if isinstance(inp, dict) and inp.get("query") else "")
    if name in ("WebFetch", "webfetch", "fetch"):
        return "Reading a web page"
    return f"Using {name}"


_partial = {}


def _opencode_model():
    """The default model in the user's OpenCode config, to name it when it fails."""
    for f in (Path.home() / ".config" / "opencode" / "opencode.json", Path.home() / ".config" / "opencode" / "opencode.jsonc"):
        try:
            m = re.search(r'"model"\s*:\s*"([^"]+)"', f.read_text())
            if m:
                return m.group(1)
        except OSError:
            pass
    return None


def _claude_partial():
    """Older Claude Code builds lack --include-partial-messages; then the answer arrives whole instead of streaming."""
    if "v" not in _partial:
        try:
            r = subprocess.run([_which("claude"), "-p", "--help"], capture_output=True, text=True, timeout=8, env=_env("claude"))
            _partial["v"] = "--include-partial-messages" in r.stdout
        except Exception:
            _partial["v"] = True
    return _partial["v"]


class Run:
    """One streaming agent run. emit(kind, payload) is called from this thread; cancel() stops it."""
    def __init__(self, provider, prompt, emit, model=None, effort=None, session=None, resume=None):
        model = model if isinstance(model, str) and re.match(r"^[A-Za-z0-9][\w.:/@+-]{0,100}$", model) else None   # never a flag
        self.provider, self.prompt, self.emit, self.model = provider, prompt, emit, model
        ok = lambda x: x if isinstance(x, str) and re.fullmatch(r"[\w-]{8,80}", x) else None   # never a flag either
        self.session, self.resume = ok(session), ok(resume)   # the agent's own session: start it with this ID, or continue it
        self.effort = effort if effort in EFFORTS else None
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def _spawn(self, args):
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     cwd=WORK_DIR, env=_env(self.provider), text=True, bufsize=1)
        threading.Thread(target=self._feed, daemon=True).start()
        self._err = []
        threading.Thread(target=lambda: self._err.extend(self.proc.stderr.readlines()[-20:]), daemon=True).start()
        killer = threading.Timer(300, self.cancel)
        killer.daemon = True
        killer.start()
        return self.proc

    def _feed(self):
        try:
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
        except Exception:
            pass

    def _finish(self):
        code = self.proc.wait() if self.proc else 0
        if self.cancelled:
            return
        if code != 0:
            tail = "".join(getattr(self, "_err", [])).strip().splitlines()[-3:]
            self.emit("error", {"message": self._explain(" ".join(tail))})

    def _explain(self, tail):
        t = tail.lower()
        if "login" in t or "auth" in t or "unauthorized" in t or "not logged in" in t:
            return f"{self.provider} isn't signed in on this Mac. Open Terminal, run `{self.provider}` once and sign in, then try again."
        if "rate" in t and "limit" in t or "usage limit" in t:
            return f"Your {self.provider} plan hit its usage limit. Try again later or pick another agent."
        return f"{self.provider} stopped unexpectedly." + (f" ({tail[:200]})" if tail else "")

    def run(self):
        try:
            getattr(self, "_run_" + self.provider)()
        except FileNotFoundError:
            self.emit("error", {"message": f"Couldn't find {self.provider} on this Mac."})
        except Exception as e:
            if not self.cancelled:
                self.emit("error", {"message": f"Something went wrong: {e}"})
        self.emit("done", {})

    # Claude Code: headless print mode, streaming JSON, read-only tools limited to the openticker command and web search
    def _run_claude(self):
        # the session is kept (in Claude Code's folder for OpenTicker's work dir) so an answer cut off by a restart can resume
        args = [_which("claude"), "-p", "--output-format", "stream-json", "--verbose"] + (["--include-partial-messages"] if _claude_partial() else []) + [
                "--strict-mcp-config", "--permission-mode", "dontAsk",
                "--tools", "Bash", "WebSearch", "WebFetch",
                "--allowedTools", "Bash(openticker:*)", "Bash(openticker *)", "WebSearch", "WebFetch"]
        if self.model:
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        if self.resume:
            args += ["--resume", self.resume]
        elif self.session:
            args += ["--session-id", self.session]
        p = self._spawn(args)
        for line in p.stdout:
            if self.cancelled:
                break
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ty = ev.get("type")
            if ty == "stream_event":
                e = ev.get("event") or {}
                if e.get("type") == "content_block_delta" and (e.get("delta") or {}).get("type") == "text_delta":
                    self.emit("text", {"text": e["delta"]["text"]})
                elif e.get("type") == "message_start" and not ev.get("parent_tool_use_id"):
                    self.emit("turn", {})
            elif ty == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        self.emit("status", {"text": _describe_tool(b.get("name"), b.get("input"))})
                    elif b.get("type") == "text" and not _partial.get("v", True) and not ev.get("parent_tool_use_id"):
                        self.emit("turn", {})
                        self.emit("text", {"text": b.get("text") or ""})
            elif ty == "system" and ev.get("subtype") == "init" and ev.get("model"):
                self.emit("meta", {"model": ev.get("model")})
            elif ty == "result":
                if ev.get("is_error"):
                    self.emit("error", {"message": self._explain(str(ev.get("result") or ""))})
                self.emit("meta", {"model": None, "ms": ev.get("duration_ms")})
        self._finish()

    # Codex: exec mode, JSON events; a sandbox that can only write to the empty work folder, with network so the openticker command works
    def _run_codex(self):
        args = [_which("codex"), "exec", "--json", "--skip-git-repo-check", "--color", "never",
                "--sandbox", "workspace-write", "-c", "sandbox_workspace_write.network_access=true"]
        if self.model:
            args += ["-m", self.model]
        if self.effort:
            args += ["-c", f'model_reasoning_effort="{self.effort}"']
        if self.resume:
            args += ["resume", self.resume, self.prompt]   # flags don't carry over a resume, so they come first again
            self.prompt = ""
        else:
            args.append("-")
        p = self._spawn(args)
        for line in p.stdout:
            if self.cancelled:
                break
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ty, item = ev.get("type"), ev.get("item") or {}
            if ty == "thread.started" and ev.get("thread_id"):
                self.emit("session", {"id": ev["thread_id"]})
            elif ty == "item.started" and item.get("type") == "command_execution":
                self.emit("status", {"text": _describe_tool("Bash", {"command": item.get("command")})})
            elif ty == "item.started" and item.get("type") == "web_search":
                self.emit("status", {"text": "Searching the web"})
            elif ty == "item.completed" and item.get("type") == "agent_message":
                self.emit("turn", {})
                self.emit("text", {"text": item.get("text") or ""})
            elif ty in ("turn.failed", "error"):
                msg = (ev.get("error") or {}).get("message") or ev.get("message") or ""
                self.emit("error", {"message": self._explain(msg)})
        self._finish()

    # opencode: `opencode run`, JSON events when supported, else plain text
    def _run_opencode(self):
        args = [_which("opencode"), "run", "--format", "json"]
        if self.model:
            args += ["--model", self.model]
        p = self._spawn(args)
        for line in p.stdout:
            if self.cancelled:
                break
            try:
                ev = json.loads(line)
            except Exception:
                if line.strip():
                    self.emit("text", {"text": line})
                continue
            part = ev.get("part") or {}
            ty = ev.get("type") or part.get("type")
            if ty == "error":
                er = ev.get("error") or {}
                msg = (er.get("message") or er.get("data", {}).get("message") or "OpenCode reported an error.").strip()
                cfg = self.model or _opencode_model()
                p.kill()
                return self.emit("error", {"message": f"OpenCode couldn't use its model{f' ({cfg})' if cfg else ''}: {msg} "
                                                      "Fix it in OpenCode, or pick another agent."})
            if ty == "text" and (part.get("text") or ev.get("text")):
                self.emit("text", {"text": part.get("text") or ev.get("text")})
            elif ty in ("tool", "tool_use"):
                st = part.get("state") or {}
                self.emit("status", {"text": _describe_tool(part.get("tool") or "tool", st.get("input") or {})})
        self._finish()

    # Ollama: local HTTP API, streamed; no tools, so the prompt carries all the data
    def _run_ollama(self):
        models = _ollama_models() or []
        model = self.model if self.model in models else (models[0] if models else None)
        if not model:
            return self.emit("error", {"message": "Ollama has no models. Run `ollama pull llama3.2` in Terminal."})
        body = json.dumps({"model": model, "stream": True, "messages": [{"role": "user", "content": self.prompt}]}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body, headers={"Content-Type": "application/json"})
        self.emit("meta", {"model": model})
        with urllib.request.urlopen(req, timeout=300) as r:
            for line in r:
                if self.cancelled:
                    break
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                t = (ev.get("message") or {}).get("content")
                if t:
                    self.emit("text", {"text": t})
                if ev.get("done"):
                    break


def context_for(scope, t, uid):
    if scope == "stock" and t:
        return stock_context(t, uid)
    if scope == "portfolio":
        return portfolio_context(uid)
    if scope == "fund" and t:
        return fund_context(t, 1) + "\n" + fund_context(t, 21)
    return market_context() + "\n" + portfolio_context(uid)


# ---------------------------------------------------------------- who may ask
def pair_token():
    s = srv.personal.settings(srv.personal.DEFAULT_USER)
    tok = s.get("ask_token")
    if not tok:
        tok = secrets.token_urlsafe(18)
        srv.personal.set_setting(srv.personal.DEFAULT_USER, "ask_token", tok)
    return tok


def is_local(handler):
    return handler.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def host_ok(handler):
    """Defeat DNS rebinding and cross-site posts: the Host must be this machine's, and any Origin must match it."""
    host = (handler.headers.get("Host") or "").lower()
    name = host.rsplit(":", 1)[0].strip("[]")
    ok = name in ("127.0.0.1", "localhost", "::1") or name.endswith(".local") or re.fullmatch(r"(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.[\d.]+", name)
    origin = handler.headers.get("Origin")
    return bool(ok) and (origin is None or origin.lower() in (f"http://{host}", f"https://{host}"))


def may_ask(handler):
    if not host_ok(handler):
        return False
    if is_local(handler):
        return True
    tok = handler.headers.get("X-Ask-Token") or ""
    return bool(tok) and secrets.compare_digest(tok, pair_token())
