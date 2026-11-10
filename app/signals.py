"""Momentum signals: the AlphaLens 3-layer score (https://alphalens-signals.vercel.app), rebuilt on Yahoo's daily bars.

A stock passes two gate filters (is there a trend at all?), collects points from six core signals and seven edge
boosters, and earns a bonus when several line up. The total maps to a rating:
  Strong Buy >= 10, Buy >= 7, Accumulate >= 4, Hold >= 1, Avoid below 1.
A failed gate caps the rating (ADX under 20: Hold at best; weekly RSI under 40: Accumulate at best).

The points and thresholds are AlphaLens's published ones. Where the site doesn't say (how recent a "cross" is, how
divergence is found), the choice is written next to the code. Two differences on purpose:
  - the sector benchmark is the SPDR sector fund (SMH for chip stocks), where AlphaLens hand-picks industry funds;
  - earnings acceleration isn't scored, as on AlphaLens today ("pending data integration").

score(bars, spy, sector) takes pandas frames/series of daily bars, oldest first, and returns a plain dict.
"""
import math

import numpy as np
import pandas as pd

RATINGS = [(10.0, "Strong Buy"), (7.0, "Buy"), (4.0, "Accumulate"), (1.0, "Hold")]
ORDER = ["Strong Buy", "Buy", "Accumulate", "Hold", "Avoid"]
CROSS_DAYS = 5      # "bullish cross last 5d", AlphaLens's window for MACD and EMA crosses
MA_CROSS_DAYS = 20  # not published: a golden or death cross counts as fresh for about a month of sessions
WINDOW = 300        # sessions each score reads: a year for the 52-week high, plus room for the 200-day and the averages to settle
HORIZONS = (21, 63)  # the track record checks a rating one and three months (21 and 63 sessions) later


def rating_for(s):
    return next((name for floor, name in RATINGS if s >= floor), "Avoid")


def _cap(rating, ceiling):
    return rating if ORDER.index(rating) >= ORDER.index(ceiling) else ceiling


# ---------------------------------------------------------------- indicators (Wilder's smoothing where traders use it)
def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(h, l, c, n=14):
    up, dn = h.diff(), -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    a = atr(h, l, c, n)
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _crossed(fast, slow, days):
    """+1 if fast crossed above slow within the last `days` bars, -1 if below, 0 if neither (the latest wins)."""
    diff = (fast - slow).dropna()
    if len(diff) < days + 1:
        return 0
    side = np.sign(diff.values[-(days + 1):])
    for i in range(len(side) - 1, 0, -1):
        if side[i] > 0 >= side[i - 1]:
            return 1
        if side[i] < 0 <= side[i - 1]:
            return -1
    return 0


def _ret(c, n):
    c = c.dropna()
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None


def _divergence(c, r, n=20):
    """Not published beyond "price and RSI(14) moving in opposite directions over 20 bars". Here: split the last 20 bars
    in halves; a lower low in price with an RSI at least 2 points higher at that low is bullish, a higher high with
    an RSI 2 points lower bearish."""
    c, r = c.iloc[-n:], r.iloc[-n:]
    if len(c) < n or r.isna().any():
        return 0
    a, b = slice(0, n // 2), slice(n // 2, n)
    lo1, lo2 = c.iloc[a].idxmin(), c.iloc[b].idxmin()
    hi1, hi2 = c.iloc[a].idxmax(), c.iloc[b].idxmax()
    if c[lo2] < c[lo1] and r[lo2] > r[lo1] + 2:
        return 1
    if c[hi2] > c[hi1] and r[hi2] < r[hi1] - 2:
        return -1
    return 0


def _vcp(h, l, w=5, look=120):
    """Volatility contraction: successive pullbacks from swing highs, each under 75% of the one before.
    Returns how many pullbacks the latest tightening run has (1 means nothing tightened yet). Swings are the extreme of w bars each side."""
    h, l = h.iloc[-look:].values, l.iloc[-look:].values
    depths, i = [], w
    while i < len(h) - w:
        if h[i] == h[i - w:i + w + 1].max():
            nxt = next((k for k in range(i + 1, len(h) - w) if h[k] == h[k - w:k + w + 1].max()), len(h))
            j = i + 1 + int(np.argmin(l[i + 1:nxt])) if nxt > i + 1 else i
            if j > i:
                depths.append((h[i] - l[j]) / h[i])
            i = max(nxt, i + 1)
        else:
            i += 1
    n = 1 if depths else 0      # the run of pullbacks, latest backwards, each under 75% of the one before
    for k in range(len(depths) - 1, 0, -1):
        if depths[k] < 0.75 * depths[k - 1]:
            n += 1
        else:
            break
    return n


def _num(x, nd=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _pct(x):
    return f"{x * 100:+.1f}%"


# ---------------------------------------------------------------- the score
def score(bars, spy, sector=None, sector_name=None):
    """bars: DataFrame with High, Low, Close, Volume (daily, oldest first, at least 220 sessions).
    spy, sector: Series of daily closes on the same calendar. Returns the rating with every signal's points and reason."""
    bars = bars.dropna(subset=["Close"]).iloc[-WINDOW:]   # the same span today and in the track record (track())
    if len(bars) < 220:
        return None
    h, l, c, v = bars["High"], bars["Low"], bars["Close"], bars["Volume"].fillna(0)
    px = float(c.iloc[-1])
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    ema8, ema21 = c.ewm(span=8, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = macd.ewm(span=9, adjust=False).mean()
    r = rsi(c)
    a_dx = float(adx(h, l, c).iloc[-1])
    wk = c.groupby(pd.to_datetime(c.index).to_period("W-FRI")).last()
    w_rsi = float(rsi(wk).iloc[-1]) if len(wk) > 15 else float("nan")
    a_tr = float(atr(h, l, c).iloc[-1])
    hi52 = float(h.iloc[-252:].max())
    from_hi = px / hi52 - 1
    uptrend = sma50.iloc[-1] > sma200.iloc[-1] and px > sma200.iloc[-1]

    spy = spy.reindex(c.index).ffill()
    rs6, rs12 = _ret(c, 126), _ret(c, 252)
    spy6, spy12 = _ret(spy, 126), _ret(spy, 252)
    rs6_spy = rs6 - spy6 if rs6 is not None and spy6 is not None else None
    rs12_spy = rs12 - spy12 if rs12 is not None and spy12 is not None else None
    sec6 = _ret(sector.reindex(c.index).ffill(), 126) if sector is not None else None
    rs6_sec = rs6 - sec6 if rs6 is not None and sec6 is not None else None
    sec_vs_spy = sec6 - spy6 if sec6 is not None and spy6 is not None else None

    core, boost, combos = [], [], []

    def add(group, name, pts, why, mx):
        group.append({"name": name, "points": pts, "max": mx, "why": why})
        return pts

    # ---- layer 2: core signals
    pts, why = 0.0, []
    if rs6_spy is not None and rs6_spy > 0:
        pts += 1.0; why.append(f"{_pct(rs6_spy)} vs the S&P 500 over 6 months")
    if rs12_spy is not None and rs12_spy > 0:
        pts += 0.5; why.append(f"{_pct(rs12_spy)} vs the S&P 500 over 12 months")
    if rs6_sec is not None and rs6_sec > 0:
        pts += 1.0; why.append(f"{_pct(rs6_sec)} vs {sector_name or 'its sector'} over 6 months")
    add(core, "Relative strength", pts, "; ".join(why) or "Not beating the S&P 500 or its sector", 2.5)

    x = _crossed(sma50, sma200, MA_CROSS_DAYS)
    above = sma50.iloc[-1] > sma200.iloc[-1]
    gc, dc = x > 0, x < 0
    if gc:
        add(core, "Moving averages", 2.5, "Golden cross: the 50-day average just crossed above the 200-day", 2.5)
    elif dc:
        add(core, "Moving averages", -3.0, "Death cross: the 50-day average just crossed below the 200-day", 2.5)
    elif above:
        add(core, "Moving averages", 1.0, "In an uptrend: the 50-day average is above the 200-day", 2.5)
    else:
        add(core, "Moving averages", -0.5, "In a downtrend: the 50-day average is below the 200-day", 2.5)   # seen on AlphaLens, not in its table

    hist = float((macd - sig).iloc[-1])
    mx = _crossed(macd, sig, CROSS_DAYS)
    pts, why = 0.0, []
    if hist > 0:
        pts += 1.0; why.append("MACD above its signal line")   # "histogram positive +0.5, above signal +0.5": the same fact twice
    if mx > 0:
        pts += 1.0; why.append("fresh bullish crossover this week")
    elif mx < 0:
        pts -= 1.5; why.append("fresh bearish crossover this week")
    why = "; ".join(why)
    add(core, "MACD momentum", pts, why[:1].upper() + why[1:] if why else "MACD below its signal line", 2.0)

    up_days = c.diff().iloc[-50:] > 0
    vv = v.iloc[-50:]
    ud = vv[up_days].mean() / vv[~up_days].mean() if (~up_days).any() and vv[~up_days].mean() > 0 else float("nan")
    if ud > 1.5:
        p, w = 2.0, "Heavy buying"
    elif ud > 1.2:
        p, w = 1.5, "Buying"
    elif ud > 1.0:
        p, w = 1.0, "Mild buying"
    elif ud < 0.8:
        p, w = -1.0, "Selling"
    else:
        p, w = 0.0, "Balanced"
    add(core, "Accumulation", p, f"{w}: up days trade {ud:.2f}× the volume of down days (50 sessions)", 2.0)

    if from_hi >= -0.05:
        p, w = 2.0, "breakout territory"
    elif from_hi >= -0.10:
        p, w = 1.0, "close to it"
    elif from_hi < -0.25:
        p, w = -0.5, "momentum broken"
    else:
        p, w = 0.0, "in between"
    add(core, "52-week high", p, f"{abs(from_hi) * 100:.1f}% below the 52-week high of ${hi52:,.2f}, {w}", 2.0)

    if sec_vs_spy is None:
        add(core, "Sector trend", 0.0, "Sector data not available", 1.0)
    elif sec_vs_spy > 0:
        add(core, "Sector trend", 1.0, f"{sector_name} is beating the S&P 500 by {sec_vs_spy * 100:.1f} points over 6 months", 1.0)
    else:
        add(core, "Sector trend", -1.0, f"{sector_name} is trailing the S&P 500 by {-sec_vs_spy * 100:.1f} points over 6 months", 1.0)

    # ---- layer 3: edge boosters
    dv = _divergence(c, r)
    add(boost, "RSI divergence", {1: 1.0, -1: -0.5, 0: 0.0}[dv],
        {1: "Bullish: price made a lower low but RSI didn't", -1: "Bearish: price made a higher high but RSI didn't",
         0: "None"}[dv], 1.0)

    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    width = (4 * sd / mid).dropna()
    sq = len(width) >= 120 and width.iloc[-1] <= width.iloc[-120:].quantile(0.10)
    add(boost, "Bollinger squeeze", 0.75 if sq else 0.0,
        "Bands as tight as they've been in six months: a big move tends to follow" if sq else "None", 0.75)

    vol_x = float(v.iloc[-1] / v.iloc[-51:-1].mean()) if v.iloc[-51:-1].mean() > 0 else 0.0
    add(boost, "Volume breakout", 1.0 if vol_x >= 1.4 else 0.0, f"Last session traded {vol_x:.1f}× its 50-day average", 1.0)

    lo14, hi14 = l.rolling(14).min(), h.rolling(14).max()
    k = (100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)).rolling(3).mean()   # slow %K
    d = k.rolling(3).mean()
    kk = float(k.iloc[-1])
    bounce = uptrend and _crossed(k, d, 3) > 0 and float(k.iloc[-4:].min()) < 20
    if bounce:
        add(boost, "Stochastic pullback", 0.75, "Bounced out of oversold inside an uptrend", 0.75)
    elif kk > 80:
        add(boost, "Stochastic pullback", -0.25, f"Overbought (%K {kk:.0f})", 0.75)
    else:
        add(boost, "Stochastic pullback", 0.0, f"Neutral (%K {kk:.0f})", 0.75)

    vcp = _vcp(h, l)
    add(boost, "Volatility contraction", 1.0 if vcp >= 3 else 0.5 if vcp == 2 else 0.0,
        f"{vcp} tighter pullbacks in a row" if vcp >= 2 else "No tightening pattern", 1.0)

    ex = _crossed(ema8, ema21, CROSS_DAYS)
    if ex > 0:
        add(boost, "EMA 8/21", 0.75, "The 8-day average just crossed above the 21-day", 0.75)
    elif ex < 0:
        add(boost, "EMA 8/21", -0.5, "The 8-day average just crossed below the 21-day", 0.75)
    elif ema8.iloc[-1] > ema21.iloc[-1]:
        add(boost, "EMA 8/21", 0.25, "The 8-day average is above the 21-day", 0.75)
    else:
        add(boost, "EMA 8/21", 0.0, "The 8-day average is below the 21-day", 0.75)

    # ---- combos
    if gc and mx > 0 and vol_x >= 1.4:
        add(combos, "Momentum ignition", 1.5, "Golden cross, MACD crossover and a volume breakout together", 1.5)
    if from_hi >= -0.10 and sq and vcp >= 2:
        add(combos, "Breakout setup", 1.0, "Near the high, bands squeezed and pullbacks tightening", 1.0)
    if (rs6_spy or 0) > 0 and (rs6_sec or 0) > 0 and a_dx > 30:
        add(combos, "Confirmed trend", 1.0, "Beating the S&P 500 and its sector in a strong trend", 1.0)
    if dv < 0 and mx < 0 and ex < 0:
        add(combos, "Divergence cluster", -2.0, "RSI divergence, MACD and EMA crosses all turning down", 0.0)

    cs, bs, xs = (round(sum(s["points"] for s in g), 2) for g in (core, boost, combos))
    total = round(cs + bs + xs, 2)
    raw = rating_for(total)
    rating, gates = raw, []
    ok = a_dx >= 20
    gates.append({"name": "Trend strength (ADX)", "pass": ok,
                  "why": f"ADX {a_dx:.0f}: " + ("a trend is there" if ok else "no clear trend, so Hold at best")})
    if not ok:
        rating = _cap(rating, "Hold")
    ok = not (w_rsi < 40)
    gates.append({"name": "Weekly RSI", "pass": ok,
                  "why": f"Weekly RSI {w_rsi:.0f}: " + ("the weekly trend holds" if ok else "the weekly trend is down, so Accumulate at best")})
    if not ok:
        rating = _cap(rating, "Accumulate")

    entry = px * 1.005
    stop = max(float(sma200.iloc[-1]) * 0.98, px - 2 * a_tr)
    if stop >= entry:
        stop = px - 2 * a_tr
    target = entry + 2.5 * (entry - stop)
    return {
        "rating": rating, "raw": raw if raw != rating else None, "score": total,
        "core": cs, "boost": bs, "combo": xs, "price": _num(px),
        "adx": _num(a_dx, 1), "rsi": _num(r.iloc[-1], 1), "wrsi": _num(w_rsi, 1),
        "fromHigh": _num(from_hi * 100, 1), "rs6": _num(rs6_spy * 100 if rs6_spy is not None else None, 1),
        "accum": _num(ud), "entry": _num(entry), "stop": _num(stop), "target": _num(target),
        "gates": gates, "signals": {"core": core, "boost": boost, "combo": combos},
    }


# ---------------------------------------------------------------- the track record
def track(bars_by_t, spy, sector_of=None, step=10, horizons=HORIZONS):
    """Scores every stock again at earlier dates, every `step` sessions, using only the bars up to that date, and
    records what the stock and the S&P 500 did in the `horizons` sessions after. No future data reaches a score.

    bars_by_t: {ticker: DataFrame of daily bars}; spy: Series of closes; sector_of: {ticker: (Series or None, name)}.
    Returns {ticker: [[date, rating, score, up_market, ret_h1, spy_h1, ret_h2, spy_h2, ...], ...]}, oldest first.
    up_market: whether the S&P 500 closed above its 200-day average that day. A return is None until it's known."""
    sector_of = sector_of or {}
    out = {}
    for t, f in bars_by_t.items():
        f = f.dropna(subset=["Close"])
        c = f["Close"]
        if len(c) < 220:
            continue
        sp = spy.reindex(c.index).ffill()
        up = (sp > sp.rolling(200, min_periods=200).mean()).values
        sec, name = sector_of.get(t) or (None, None)
        rows = []
        for i in range(len(c) - 1, 218, -step):
            try:
                r = score(f.iloc[:i + 1], spy, sec, name)
            except Exception:
                r = None
            if not r:
                continue
            row = [c.index[i].strftime("%Y-%m-%d"), r["rating"], r["score"], bool(up[i]) if i >= 199 else None]
            for h in horizons:
                ok = i + h < len(c) and c.iloc[i] and sp.iloc[i] == sp.iloc[i]
                row += [_num(c.iloc[i + h] / c.iloc[i] - 1, 4), _num(sp.iloc[i + h] / sp.iloc[i] - 1, 4)] if ok else [None, None]
            rows.append(row)
        out[t] = rows[::-1]
    return out


def track_summary(stocks, horizons=HORIZONS):
    """How each rating did afterwards: per horizon, the number of cases, the average return, the average lead over the
    S&P 500 and the share that beat it. Also split by whether the market was above its 200-day then, since momentum
    tends to work better in a rising market. "All" is every stock and date, the yardstick each rating is judged against."""
    def agg(rows, k):
        got = [(r[4 + 2 * k], r[5 + 2 * k]) for r in rows if r[4 + 2 * k] is not None and r[5 + 2 * k] is not None]
        if not got:
            return {"n": 0}
        n = len(got)
        return {"n": n, "avg": _num(sum(a for a, _ in got) / n, 4), "vs": _num(sum(a - b for a, b in got) / n, 4),
                "beat": _num(sum(1 for a, b in got if a > b) / n, 3)}
    rows = [r for v in stocks.values() for r in v]
    out = {"horizons": list(horizons), "ratings": {}, "upMarket": {}, "downMarket": {}}
    for name, keep in (("ratings", lambda r: True), ("upMarket", lambda r: r[3] is True), ("downMarket", lambda r: r[3] is False)):
        for rating in ORDER + ["All"]:
            sel = [r for r in rows if keep(r) and (rating == "All" or r[1] == rating)]
            out[name][rating] = {str(h): agg(sel, k) for k, h in enumerate(horizons)}
    dates = sorted(r[0] for r in rows)
    out["from"], out["to"] = (dates[0], dates[-1]) if dates else (None, None)
    out["stocks"] = len(stocks)
    return out


def breadth(bars_by_t, back=21):
    """The share of stocks above their 50- and 200-day averages, now and `back` sessions ago. Most stocks above their
    200-day is a healthy market; few, a weak one, where buy signals fail more often."""
    def share(k, ago):
        ok = tot = 0
        for f in bars_by_t.values():
            c = f["Close"].dropna()
            if len(c) < k + ago + 1:
                continue
            tot += 1
            ok += c.iloc[-1 - ago] > c.iloc[-1 - ago - k + 1:len(c) - ago].mean()
        return _num(ok / tot, 3) if tot else None, tot
    (a50, n), (a200, _), (a50b, _), (a200b, _) = share(50, 0), share(200, 0), share(50, back), share(200, back)
    return {"above50": a50, "above200": a200, "above50Then": a50b, "above200Then": a200b, "n": n, "back": back}
