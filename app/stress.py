"""Under the hood: a few gauges of whether a selloff is spreading or staying put.

Each gauge answers one question a careful investor asks when stocks fall, and says calm, watch or stressed:

  credit   Are lenders getting nervous?          Junk bond spread over Treasuries (FRED, ICE BofA series)
  fear     How scared are options traders?       VIX (Yahoo)
  breadth  Is the selling broad or narrow?       Equal-weight S&P 500 (RSP) against the index (SPY), from their highs
  appetite Are investors fleeing risky stocks?   High-beta (SPHB) against low-volatility (SPLV) stocks over a month
  funds    Are hedge funds moving fast?          Leveraged funds' net position in S&P 500 and Nasdaq-100 futures (CFTC)

The fetchers here only download and parse; the readings are pure functions of the numbers, so tests can feed them
fixed series. server.py caches each source (`stress_payload`), so FRED and the CFTC are asked a few times a day.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import subprocess
from bisect import bisect_right
from urllib.parse import urlencode

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CFTC_TFF = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"   # Traders in Financial Futures, futures only
CREDIT_SERIES = "BAMLH0A0HYM2"         # ICE BofA US High Yield Index option-adjusted spread, percent
CFTC_MARKETS = {"13874+": "S&P 500", "20974+": "Nasdaq-100"}   # CME consolidated contracts (E-mini and micro together)
PRICES = ["^VIX", "SPY", "RSP", "SPHB", "SPLV"]
STATES = ("calm", "watch", "stressed")


def _get(url: str) -> bytes:
    # curl, like the fund holdings downloads: it uses the Mac's own certificates and proxy settings. Keep curl's own
    # user agent: FRED's front end resets the connection for unfamiliar ones (seen 2026-11-20 with "OpenTicker/1.0")
    out = subprocess.run(["curl", "-fsSL", "--connect-timeout", "10", "-m", "25", url], capture_output=True, check=True)
    return out.stdout


def fred(series: str, years: int = 3):
    """[(date, value)] for a FRED series, oldest first. FRED's CSV leaves a blank or "." on days with no value."""
    start = (dt.date.today() - dt.timedelta(days=365 * years + 7)).isoformat()
    raw = _get(f"{FRED_CSV}?{urlencode({'id': series, 'cosd': start})}").decode("utf-8", "replace")
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows or len(rows[0]) < 2 or rows[0][1] != series:
        raise ValueError(f"FRED sent something other than {series}")
    out = []
    for r in rows[1:]:
        try:
            out.append((r[0], float(r[1])))
        except (ValueError, IndexError):
            continue
    if len(out) < 30:
        raise ValueError(f"FRED sent only {len(out)} values for {series}")
    return out


def cftc(years: int = 3):
    """{market: [(date, long, short, open interest)]} for leveraged funds, oldest first. The report is as of Tuesday
    and comes out on Friday afternoon."""
    since = (dt.date.today() - dt.timedelta(days=365 * years + 14)).isoformat()
    codes = ",".join(f"'{c}'" for c in CFTC_MARKETS)
    q = {"$select": "cftc_contract_market_code as c,report_date_as_yyyy_mm_dd as d,lev_money_positions_long as l,"
                    "lev_money_positions_short as s,open_interest_all as oi",
         "$where": f"cftc_contract_market_code in({codes}) and report_date_as_yyyy_mm_dd > '{since}'",
         "$order": "d", "$limit": "5000"}
    rows = json.loads(_get(f"{CFTC_TFF}?{urlencode(q)}"))
    out = {m: [] for m in CFTC_MARKETS.values()}
    for r in rows:
        m = CFTC_MARKETS.get(r.get("c"))
        try:
            out[m].append((str(r["d"])[:10], float(r["l"]), float(r["s"]), float(r["oi"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not all(len(v) >= 20 for v in out.values()):
        raise ValueError("the CFTC sent too few weeks")
    return out


# ---------------------------------------------------------------- readings
# Every gauge reads each past day the same way it reads today, so the trend and today's card always agree. A gauge's
# "hist" is {d: dates, v: the measure, s: 0 calm / 1 watch / 2 stressed, bands: [watch, stressed] on v when the state
# follows from v alone, fmt: how to print v}; the Market page draws it, and payload() lines them up into a timeline.
def _pct_rank(xs, x):
    """Share of xs at or below x, 0 to 1."""
    xs = [v for v in xs if v is not None]
    return sum(1 for v in xs if v <= x) / len(xs) if xs else None


def _ago(vals, n):
    return vals[-1 - n] if len(vals) > n else None


def _st(x, watch, stressed):
    """0 calm, 1 watch, 2 stressed. Thresholds below zero mean lower is worse."""
    if stressed < 0:
        return 2 if x <= stressed else 1 if x <= watch else 0
    return 2 if x >= stressed else 1 if x >= watch else 0


def _hist(dates, vals, states, start=0, **extra):
    h = {"d": list(dates[start:]), "v": [round(v, 4) for v in vals[start:]], "s": list(states[start:])}
    h.update(extra)
    return h


def _spark(h, n=252):
    return h["v"][-n:]


def credit(series):
    """series: [(date, spread in percentage points)]. The long-run middle of this spread is about 4.5 to 5 points; it
    rose past 8 in 2020 and 2008. A fast rise matters more than the level: lenders widen spreads when they start to
    worry about getting paid back, and stock selloffs that reach credit have tended to last longer."""
    dates, vals = [d for d, _ in series], [v for _, v in series]
    ch = [vals[i] - vals[i - 21] if i >= 21 else 0.0 for i in range(len(vals))]
    st = [max(_st(v, 4.5, 5.5), _st(c, 0.35, 0.75)) for v, c in zip(vals, ch)]
    h = _hist(dates, vals, st, fmt="pts", bands=[4.5, 5.5], vname="Junk bond spread",
              rule="Watch at 4.5 points or a rise of 0.35 in a month; stressed at 5.5 or a rise of 0.75.")
    last, state = vals[-1], STATES[st[-1]]
    rank = _pct_rank(vals, last)
    meaning = {"calm": "Lenders aren't asking much more to lend to riskier companies, so the stress hasn't reached bonds.",
               "watch": "Lenders are starting to ask more to lend to riskier companies. Worth watching if it keeps rising.",
               "stressed": "Lenders are pulling back from riskier companies. Selloffs that reach bonds have tended to last longer."}[state]
    return {"key": "credit", "name": "Credit", "question": "Are lenders getting nervous?", "state": state,
            "value": f"{last:.2f} pts", "line": f"Junk bonds pay {last:.2f} points over Treasuries, {_pts(ch[-1])} in a month.",
            "meaning": meaning, "note": _rank_note(rank, "the last three years"), "unit": "over Treasuries",
            "asOf": dates[-1], "spark": _spark(h), "hist": h, "source": "ICE BofA US High Yield spread, from FRED",
            "data": {"last": last, "chg1m": round(ch[-1], 3)}}


def fear(dates, vix):
    """VIX: what S&P 500 options imply for the size of daily swings over the next month. Below 20 is ordinary; above
    30 has come with the sharpest selloffs, and spikes that high have often come near the worst days, though not always."""
    st = [_st(v, 20, 30) for v in vix]
    h = _hist(dates, vix, st, fmt="num", bands=[20, 30], vname="VIX", rule="Watch at 20; stressed at 30.")
    last, w1, state = vix[-1], _ago(vix, 5), STATES[st[-1]]
    rank = _pct_rank(vix[-252:], last)
    meaning = {"calm": "Options traders expect an ordinary month.",
               "watch": "Traders are paying up for protection. Expect bigger daily swings than usual.",
               "stressed": "Fear is high. Spikes like this have often come near the worst of a selloff, but not always."}[state]
    swing = last / 15.87   # VIX / sqrt(252): the typical daily move it implies, in percent
    return {"key": "fear", "name": "Fear", "question": "How scared are options traders?", "state": state,
            "value": f"{last:.1f}", "line": f"The VIX is {last:.1f}" + (f", {_pts(last - w1, 1, '')} this week." if w1 else ".")
            + f" Traders expect daily moves of about {swing:.1f}%.",
            "meaning": meaning, "note": _rank_note(rank, "the past year"), "unit": "VIX",
            "asOf": dates[-1], "spark": _spark(h), "hist": h, "source": "Cboe VIX, from Yahoo", "data": {"last": last}}


def _drawdowns(a, w=252):
    """Each day's distance below the highest close of the year before it (w days), from the first full year on."""
    w = min(w, len(a))
    return [a[i] / max(a[i - w + 1:i + 1]) - 1 for i in range(w - 1, len(a))], w - 1


def breadth(dates, rsp, spy):
    """How far the typical S&P 500 stock (the equal-weight fund) is below its high for the year, against the index
    itself, which the biggest companies dominate. If the typical stock holds up while the index falls, the selling is
    narrow: a few crowded names, not the whole market."""
    de, start = _drawdowns(rsp)
    ds, _ = _drawdowns(spy)
    st = [_st(x, -0.04, -0.10) for x in de]
    h = _hist(dates[start:], de, st, fmt="pct", bands=[-0.04, -0.10], v2=[round(x, 4) for x in ds], v2name="S&P 500 index",
              vname="Typical stock", rule="Watch when the typical stock is 4% below its high for the year; stressed at 10%.")
    e, s, state = de[-1], ds[-1], STATES[st[-1]]
    narrow, broad = e > s + 0.01, e < s - 0.01
    meaning = ("The selling is mostly in the biggest companies; the typical stock is holding up better." if narrow else
               "The selling is broad: the typical stock is down more than the index." if broad else
               "The typical stock and the index are about the same distance from their highs.")
    return {"key": "breadth", "name": "Breadth", "question": "Is the selling broad or narrow?", "state": state,
            "value": f"{e * 100:.1f}%", "line": f"The average S&P 500 stock is {abs(e) * 100:.1f}% below its high, the index {abs(s) * 100:.1f}%.",
            "meaning": meaning, "unit": "typical stock, from its high", "note": "The line is the typical stock's distance from its high.",
            "asOf": dates[-1], "spark": _spark(h), "hist": h,
            "source": "Equal-weight S&P 500 (RSP) and the S&P 500 (SPY), from Yahoo",
            "data": {"equal": e, "index": s, "narrow": narrow, "broad": broad}}


def appetite(dates, hb, lv):
    """High-beta stocks (the S&P 500's 100 most volatile) against low-volatility ones over the past month. When money
    that was borrowed to own the riskiest names gets pulled, they fall far more than steady ones."""
    ratio = [a / b for a, b in zip(hb, lv)]
    start = min(21, len(ratio) - 1)
    chs = [ratio[i] / ratio[i - start] - 1 for i in range(start, len(ratio))]
    st = [_st(x, -0.04, -0.10) for x in chs]
    h = _hist(dates[start:], chs, st, fmt="pct", bands=[-0.04, -0.10], vname="Risky vs steady, one month",
              rule="Watch when risky stocks trail steady ones by 4% over a month; stressed at 10%.")
    ch, state = chs[-1], STATES[st[-1]]
    meaning = {"calm": "Investors are still willing to own risky stocks.",
               "watch": "Money is moving from risky stocks to steady ones.",
               "stressed": "A rush out of risky stocks, the kind that comes when borrowed money is being pulled."}[state]
    line = (f"Risky stocks did {abs(ch) * 100:.1f}% worse than steady ones over the past month." if ch < -0.005 else
            f"Risky stocks did {ch * 100:.1f}% better than steady ones over the past month." if ch > 0.005 else
            "Risky and steady stocks did about the same over the past month.")
    return {"key": "appetite", "name": "Risk appetite", "question": "Are investors fleeing risky stocks?", "state": state,
            "value": f"{ch * 100:+.1f}%", "line": line, "meaning": meaning, "unit": "risky vs steady, past month",
            "note": "The line is risky stocks against steady ones over each month: below zero, investors are pulling back.",
            "asOf": dates[-1], "spark": _spark(h), "hist": h,
            "source": "S&P 500 High Beta (SPHB) and Low Volatility (SPLV) funds, from Yahoo", "data": {"chg1m": ch}}


def funds(by_market):
    """Leveraged funds (hedge funds and other speculators) in stock index futures: long minus short, as a share of all
    open contracts. They are usually short S&P 500 futures as the other side of bond and basis trades, so the level
    says little; how fast it moves says more. A four-week shift bigger than almost any in three years means funds are
    being forced to reposition, which is how leverage comes out of the market."""
    parts, worst, by_date = [], None, {}
    for m, rows in by_market.items():
        rows = [r for r in rows if r[3]]
        if len(rows) < 10:
            continue
        dates, net = [r[0] for r in rows], [(r[1] - r[2]) / r[3] for r in rows]
        moves = [abs(net[i] - net[i - 4]) for i in range(4, len(net))]
        # strictly bigger: a quiet week isn't a record
        ranks = [sum(1 for x in moves if x < abs(net[i] - net[i - 4])) / len(moves) if i >= 4 else 0.0 for i in range(len(net))]
        for d, r in zip(dates, ranks):
            by_date[d] = max(by_date.get(d, 0), 2 if r >= 0.95 else 1 if r >= 0.80 else 0)
        parts.append({"market": m, "net": net[-1], "was": net[-5], "chg4w": net[-1] - net[-5], "rank": ranks[-1],
                      "asOf": dates[-1], "d": dates, "v": net})
        if worst is None or ranks[-1] > worst["rank"]:
            worst = parts[-1]
    if not worst:
        raise ValueError("no futures positions")
    main = parts[0]
    other = parts[1] if len(parts) > 1 else None
    v2 = None
    if other:
        o = dict(zip(other["d"], other["v"]))
        v2 = [round(o[d], 4) if d in o else None for d in main["d"]]
    h = _hist(main["d"], main["v"], [by_date[d] for d in main["d"]], fmt="pct", bands=None, vname=f"{main['market']} futures",
              v2=v2, v2name=f"{other['market']} futures" if other else None,
              rule="Each line is long minus short as a share of all contracts. Watch when a four-week shift in either is "
                   "bigger than 80% of the past three years' shifts; stressed above 95%.")
    r = worst["rank"]
    state = STATES[by_date[worst["asOf"]]]
    meaning = {"calm": "Hedge funds are changing their futures bets at a normal pace.",
               "watch": "Hedge funds are repositioning faster than usual.",
               "stressed": "Hedge funds are repositioning faster than almost any time in three years, a sign of forced moves."}[state]

    def pos(x, of=" of contracts"):
        return "about even" if abs(x) < 0.005 else f"net {'long' if x > 0 else 'short'} {abs(x) * 100:.0f}%{of}"
    line = " ".join(f"{p['market']}: {pos(p['net'])}" + (", about where it was a month earlier." if abs(p["chg4w"]) < 0.01
                    else f", from {pos(p['was'], '')} a month earlier.") for p in parts)
    return {"key": "funds", "name": "Hedge funds", "question": "Are hedge funds moving fast?", "state": state,
            "value": f"{abs(worst['chg4w']) * 100:.0f} pts", "line": line, "meaning": meaning, "unit": f"{worst['market']} shift in 4 weeks",
            "note": ("The biggest four-week shift in three years." if r >= 0.995 else f"Bigger than {r * 100:.0f}% of four-week shifts in three years.")
            + f" The line is their {main['market']} position, long minus short.",
            "asOf": worst["asOf"], "spark": _spark(h, 52), "hist": h, "weekly": True,
            "source": "CFTC Traders in Financial Futures, leveraged funds; as of Tuesday, out each Friday",
            "data": {"parts": [{k: v for k, v in p.items() if k not in ("d", "v")} for p in parts]}}


def _rank_note(rank, span):
    if rank is None:
        return ""
    if rank >= 0.995:
        return f"The highest in {span}."
    if rank <= 0.005:
        return f"The lowest in {span}."
    return f"Higher than {rank * 100:.0f}% of days in {span}."


def _pts(x, nd=2, unit=" pts"):
    if abs(x) < 0.5 * 10 ** -nd:
        return "flat"
    return f"{'up' if x > 0 else 'down'} {abs(x):.{nd}f}{unit}"


def summary(g):
    """One headline across the gauges, in the order a careful reader checks them: has it reached credit, is it broad,
    how loud is it in stocks."""
    by = {x["key"]: x for x in g if x.get("state")}
    if not by:
        return None, None
    n = sum(1 for x in by.values() if x["state"] != "calm")
    c, b = by.get("credit"), by.get("breadth")
    stock = [by[k] for k in ("fear", "appetite", "funds") if k in by and by[k]["state"] != "calm"]
    if n == 0:
        head = "Calm under the hood"
    elif c and c["state"] == "stressed":
        head = "The stress has reached the bond market"
    elif c and c["state"] == "watch":
        head = "Stocks are shaken, and bonds are starting to notice"
    elif c:
        head = "Stocks are shaken, but bonds are calm" if stock else "Mostly calm, with a few things to watch"
    else:
        head = "Stocks are shaken" if stock else "Mostly calm"
    sub = None
    if b and b["data"].get("narrow") and b["data"]["index"] < -0.03:
        sub = "The selling is concentrated in the biggest companies; the typical stock is holding up better."
    elif b and b["data"].get("broad") and b["data"]["equal"] < -0.03:
        sub = "The selling is broad, not just in the biggest companies."
    return head, sub


def payload(credit_series=None, prices=None, cftc_rows=None, errors=None):
    """Everything the Market page and Tick need. Any source can be missing: its gauge says so and the rest still show.
    prices: {"dates": [...], "px": {sym: [...]}} with no gaps (the caller trims to dates where all are present)."""
    errors = dict(errors or {})
    g = []

    def add(key, name, question, fn):
        try:
            g.append(fn())
        except Exception as e:
            g.append({"key": key, "name": name, "question": question, "state": None,
                      "error": errors.get(key) or f"Not available right now ({type(e).__name__})."})

    add("credit", "Credit", "Are lenders getting nervous?", lambda: credit(credit_series))
    d, px = (prices or {}).get("dates"), (prices or {}).get("px") or {}
    add("breadth", "Breadth", "Is the selling broad or narrow?", lambda: breadth(d, px["RSP"], px["SPY"]))
    add("appetite", "Risk appetite", "Are investors fleeing risky stocks?", lambda: appetite(d, px["SPHB"], px["SPLV"]))
    add("fear", "Fear", "How scared are options traders?", lambda: fear(d, px["^VIX"]))
    add("funds", "Hedge funds", "Are hedge funds moving fast?", lambda: funds(cftc_rows))
    for x in g:      # a real minus sign, as the page shows everywhere else
        if isinstance(x.get("value"), str):
            x["value"] = x["value"].replace("-", "\u2212")
    head, sub = summary(g)
    tl = timeline(g)
    for x in g:      # two years is all the page shows
        h = x.get("hist")
        if h:
            n = 110 if x.get("weekly") else 520
            for k in ("d", "v", "s", "v2"):
                if h.get(k):
                    h[k] = h[k][-n:]
    return {"head": head, "sub": sub, "gauges": g, "timeline": tl}


def _day(d, today=None):
    x = dt.date.fromisoformat(d)
    today = today or dt.date.today()
    return f"{x:%b} {x.day}" + ("" if x.year == today.year else f", {x.year}")


def timeline(g, keep=520):
    """Every trading day's reading for each gauge, lined up on the price days: s is one string per day, a character
    per gauge in g's order ("0" calm, "1" watch, "2" stressed, "-" no reading). The weekly hedge fund report counts
    from the Friday it comes out, and a reading more than ten days old counts as none."""
    base = next((x for x in g if x.get("hist") and not x.get("weekly") and x["key"] != "credit"), None) \
        or next((x for x in g if x.get("hist")), None)
    if not base:
        return None
    days = base["hist"]["d"][-keep:]
    cols = []
    for x in g:
        h = x.get("hist")
        if not h:
            cols.append(None)
            continue
        hd = h["d"]
        if x.get("weekly"):
            hd = [(dt.date.fromisoformat(d) + dt.timedelta(days=3)).isoformat() for d in hd]
        cols.append((hd, [dt.date.fromisoformat(d) for d in hd], h["s"]))
    rows = []
    for d in days:
        day, row = dt.date.fromisoformat(d), ""
        for c in cols:
            i = bisect_right(c[0], d) - 1 if c else -1
            row += str(c[2][i]) if i >= 0 and (day - c[1][i]).days <= 10 else "-"
        rows.append(row)
    tl = {"d": days, "s": rows, "keys": [x["key"] for x in g], "names": [x["name"] for x in g]}
    tl["note"] = timeline_note(tl)
    return tl


def timeline_note(tl, today=None):
    """Today's count of stressed gauges, how long it has lasted and when it last happened before."""
    d, cnt = tl["d"], [r.count("2") for r in tl["s"]]
    if not d:
        return ""
    n, have = cnt[-1], sum(1 for c in tl["s"][-1] if c != "-")
    span = "the past two years" if len(d) > 400 else "the past year"
    if n == 0:
        last = next((d[i] for i in range(len(d) - 1, -1, -1) if cnt[i]), None)
        return "No gauge is stressed today." + (f" The last stressed day was {_day(last, today)}." if last else f" None has been in {span}.")
    i = len(cnt) - 1
    while i > 0 and cnt[i - 1] >= n:
        i -= 1
    word = "gauge is" if n == 1 else "gauges are"
    out = f"{n} of {have} {word} stressed today" + (f", and {'it has' if n == 1 else 'that many have'} been since {_day(d[i], today)}." if i < len(d) - 1 else ".")
    prev = next((j for j in range(i - 1, -1, -1) if cnt[j] >= n), None)
    out += (f" Before that, the last time was {_day(d[prev], today)}." if prev is not None else
            f" That hadn't happened before in {span}." if i > 0 else "")
    return out


def trend_line(x, days=63):
    """How a gauge read over roughly the last three months, for Tick."""
    h = x.get("hist") or {}
    s = h.get("s") or []
    n = 13 if x.get("weekly") else days
    s, d = s[-n:], (h.get("d") or [])[-n:]
    if not s:
        return ""
    unit = "weeks" if x.get("weekly") else "trading days"
    first = next((d[i] for i in range(len(s)) if s[i] == 2), None)
    return (f"Past three months: stressed {s.count(2)} of {len(s)} {unit}, watch {s.count(1)}"
            + (f"; first stressed on {first}." if first else "."))


def text(p):
    """The gauges as Markdown for Tick."""
    if not p or not p.get("gauges"):
        return ""
    L = ["## Under the hood (is a selloff spreading?)"]
    if p.get("head"):
        L.append(p["head"] + "." + (" " + p["sub"] if p.get("sub") else ""))
    if (p.get("timeline") or {}).get("note"):
        L.append(p["timeline"]["note"])
    for x in p["gauges"]:
        if x.get("state"):
            L.append(f"- {x['name']} ({x['question'].rstrip('?').lower()}): **{x['state']}**. {x['line']} {x['meaning']} "
                     f"{x.get('note', '')} {trend_line(x)} Rule: {(x.get('hist') or {}).get('rule', '')} "
                     f"Source: {x['source']}, as of {x['asOf']}.".rstrip())
        else:
            L.append(f"- {x['name']}: not available right now.")
    return "\n".join(L)
