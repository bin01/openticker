"""Everything beyond prices and holdings that Yahoo Finance offers, shaped for the dashboard.

Each function returns plain JSON-able data. Callers cache results (see server.cached).
Personal use only: these are Yahoo's unofficial endpoints, reached through yfinance.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import time

import pandas as pd
import yfinance as yf

NY = "America/New_York"


# ---------------------------------------------------------------- helpers
def clean(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int,)):
        return v
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        try:
            return v.isoformat()[:10] if isinstance(v, dt.date) and not isinstance(v, dt.datetime) else pd.Timestamp(v).isoformat()
        except Exception:
            return str(v)
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, str):
        return v
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return str(v)


def records(df: pd.DataFrame | None, index_name: str | None = None, limit: int | None = None):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    d = df.copy()
    if index_name:
        d = d.reset_index().rename(columns={"index": index_name, d.index.name or "index": index_name})
    out = [clean(r) for r in d.to_dict("records")]
    return out[:limit] if limit else out


def table_by_period(df: pd.DataFrame | None):
    """Yahoo's estimate tables are indexed by period (0q, +1q, 0y, +1y): return {period: {col: val}}."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    return {str(i): clean(r) for i, r in zip(df.index, df.to_dict("records"))}


def _need(out, *keys):
    """yfinance often logs a 401/429 and hands back empty data instead of raising. Raise, so the cache
    keeps the last good copy (or the page shows a retry) rather than storing an empty answer for hours."""
    if not any(out.get(k) for k in keys):
        raise RuntimeError("Yahoo didn't send this data just now. Try again in a minute.")
    return out


def iso(ts):
    try:
        return pd.Timestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return None


# ---------------------------------------------------------------- analysts
def analysts(sym):
    t = yf.Ticker(sym)
    out = {"t": sym}
    try:
        out["trend"] = records(t.recommendations_summary)
    except Exception:
        out["trend"] = []
    try:
        ud = t.upgrades_downgrades
        rows = []
        if isinstance(ud, pd.DataFrame) and not ud.empty:
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)
            ud = ud[ud.index >= cutoff].sort_index(ascending=False)
            for ts, r in zip(ud.index, ud.to_dict("records")):
                rows.append({"date": iso(ts), "firm": r.get("Firm"), "to": r.get("ToGrade"), "from": r.get("FromGrade"),
                             "action": r.get("Action"), "ptAction": r.get("priceTargetAction"),
                             "pt": clean(r.get("currentPriceTarget")), "ptPrior": clean(r.get("priorPriceTarget"))})
        out["changes"] = rows[:40]
    except Exception:
        out["changes"] = []
    for name in ("eps_trend", "eps_revisions", "earnings_estimate", "revenue_estimate", "growth_estimates"):
        try:
            out[name] = table_by_period(getattr(t, name))
        except Exception:
            out[name] = {}
    try:
        out["targets"] = clean(t.analyst_price_targets or {})
    except Exception:
        out["targets"] = {}
    return _need(out, "trend", "changes", "eps_trend", "earnings_estimate", "targets")


# ---------------------------------------------------------------- financials
FIN_ROWS = {
    "income": [("Total Revenue", "Revenue"), ("Gross Profit", "Gross profit"), ("Operating Income", "Operating income"),
               ("Net Income", "Net income"), ("Diluted EPS", "EPS (diluted)"), ("Research And Development", "R&D")],
    "cashflow": [("Operating Cash Flow", "Operating cash flow"), ("Capital Expenditure", "Capital spending"),
                 ("Free Cash Flow", "Free cash flow"), ("Repurchase Of Capital Stock", "Buybacks"),
                 ("Cash Dividends Paid", "Dividends paid")],
    "balance": [("Cash Cash Equivalents And Short Term Investments", "Cash and investments"), ("Total Debt", "Total debt"),
                ("Stockholders Equity", "Shareholders' equity"), ("Ordinary Shares Number", "Shares outstanding")],
}


def _fin(df, rows):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {"periods": [], "rows": []}
    cols = sorted(df.columns, key=lambda c: pd.Timestamp(c))[-8:]
    out = {"periods": [iso(c) for c in cols], "rows": []}
    for key, label in rows:
        if key in df.index:
            out["rows"].append({"key": key, "label": label, "values": [clean(df.at[key, c]) for c in cols]})
    return out


def financials(sym):
    t = yf.Ticker(sym)
    out = {"t": sym}
    for freq, getter in (("quarterly", lambda n: getattr(t, f"quarterly_{n}")), ("annual", lambda n: getattr(t, n))):
        block = {}
        for part, attr in (("income", "income_stmt"), ("cashflow", "cashflow"), ("balance", "balance_sheet")):
            try:
                block[part] = _fin(getter(attr), FIN_ROWS[part])
            except Exception:
                block[part] = {"periods": [], "rows": []}
        out[freq] = block
    _need({f: out[f]["income"]["periods"] for f in ("quarterly", "annual")}, "quarterly", "annual")
    return out


# ---------------------------------------------------------------- ownership
def ownership(sym):
    t = yf.Ticker(sym)
    out = {"t": sym}
    try:
        mh = t.major_holders
        out["major"] = {str(k): clean(v) for k, v in zip(mh.index, mh["Value"].tolist())} if isinstance(mh, pd.DataFrame) and not mh.empty else {}
    except Exception:
        out["major"] = {}
    for key, attr in (("institutions", "institutional_holders"), ("funds", "mutualfund_holders")):
        try:
            out[key] = [{"holder": r.get("Holder"), "pct": clean(r.get("pctHeld")), "shares": clean(r.get("Shares")),
                         "value": clean(r.get("Value")), "chg": clean(r.get("pctChange")), "date": iso(r.get("Date Reported"))}
                        for r in getattr(t, attr).to_dict("records")][:10]
        except Exception:
            out[key] = []
    try:
        it = t.insider_transactions
        rows = []
        if isinstance(it, pd.DataFrame) and not it.empty:
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=365)
            for r in it.to_dict("records"):
                d = pd.Timestamp(r.get("Start Date")) if r.get("Start Date") is not None else None
                if d is not None and d < cutoff:
                    continue
                text = str(r.get("Text") or "")
                kind = ("buy" if re.search(r"Purchase|Buy", text, re.I) else
                        "sell" if re.search(r"Sale|Sell", text, re.I) else
                        "award" if re.search(r"Award|Grant|Gift|Conversion|Exercise", text, re.I) else "other")
                # a finer label than `kind` (which the page uses): exercises and gifts aren't pay, and aren't trades either
                what = ("exercise" if re.search(r"Conversion|Exercise", text, re.I) else
                        "gift" if re.search(r"Gift", text, re.I) else kind)
                px = re.search(r"price\s+([\d,.]+)", text, re.I)
                rows.append({"date": iso(d), "insider": r.get("Insider"), "role": r.get("Position"), "text": text,
                             "shares": clean(r.get("Shares")), "value": clean(r.get("Value")), "kind": kind, "what": what,
                             "price": clean(float(px.group(1).replace(",", ""))) if px else None, "own": r.get("Ownership")})
        out["insiders"] = rows[:100]
    except Exception:
        out["insiders"] = []
    try:
        ro = t.insider_roster_holders
        out["roster"] = [{"name": r.get("Name"), "role": r.get("Position"), "last": r.get("Most Recent Transaction"),
                          "lastDate": iso(r.get("Latest Transaction Date")),
                          "direct": clean(r.get("Shares Owned Directly")), "indirect": clean(r.get("Shares Owned Indirectly"))}
                         for r in ro.to_dict("records")] if isinstance(ro, pd.DataFrame) else []
    except Exception:
        out["roster"] = []
    try:
        ip = t.insider_purchases
        out["insiderSummary"] = [{"label": str(r.iloc[0]), "shares": clean(r.iloc[1]), "trans": clean(r.iloc[2])}
                                 for _, r in ip.iterrows()] if isinstance(ip, pd.DataFrame) else []
    except Exception:
        out["insiderSummary"] = []
    return _need(out, "major", "institutions", "funds", "insiders")


# ---------------------------------------------------------------- daily bars (for technicals)
def ohlc(sym):
    """Two years of daily bars, split-adjusted, oldest first."""
    h = yf.Ticker(sym).history(period="2y", interval="1d", auto_adjust=True)
    if h is None or h.empty:
        raise RuntimeError("Yahoo didn't send price history just now. Try again in a minute.")
    h = h.dropna(subset=["Close"])
    return {"d": [i.strftime("%Y-%m-%d") for i in h.index], "o": [clean(x) for x in h["Open"]], "h": [clean(x) for x in h["High"]],
            "l": [clean(x) for x in h["Low"]], "c": [clean(x) for x in h["Close"]], "v": [clean(x) for x in h["Volume"]]}


# ---------------------------------------------------------------- options
def _mid(row):
    b, a, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if b and a and a >= b > 0:
        return (a + b) / 2
    return last or None


def options(sym, earnings_date: str | None = None, expiry: str | None = None):
    t = yf.Ticker(sym)
    exps = list(t.options or [])
    if not exps:
        return {"t": sym, "expirations": []}
    price = None
    try:
        price = t.fast_info["last_price"]
    except Exception:
        pass
    today = dt.date.today()

    def chain(e):
        c = t.option_chain(e)
        return c.calls, c.puts

    def atm(e):
        calls, puts = chain(e)
        if calls.empty or puts.empty or not price:
            return None
        k = min(calls["strike"], key=lambda s: abs(s - price))
        cr = calls[calls["strike"] == k].iloc[0].to_dict()
        pr = puts[puts["strike"] == k].iloc[0].to_dict() if (puts["strike"] == k).any() else None
        cm, pm = _mid(cr), (_mid(pr) if pr else None)
        days = max((dt.date.fromisoformat(e) - today).days, 0)
        straddle = (cm or 0) + (pm or 0) if cm and pm else None
        iv = cr.get("impliedVolatility")
        return {"expiry": e, "days": days, "strike": clean(k), "straddle": clean(straddle),
                "move": clean(straddle / price if straddle and price else None), "iv": clean(iv)}

    out = {"t": sym, "price": clean(price), "expirations": exps[:24]}
    near = next((e for e in exps if (dt.date.fromisoformat(e) - today).days >= 2), exps[0])
    try:
        out["near"] = atm(near)
    except Exception:
        out["near"] = None
    if earnings_date:
        after = next((e for e in exps if e >= earnings_date), None)
        if after:
            try:
                out["earnings"] = {**(atm(after) or {}), "earningsDate": earnings_date}
            except Exception:
                pass
    # put/call and unusual activity across the first three expiries
    cv = pv = coi = poi = 0
    unusual = []
    for e in exps[:3]:
        try:
            calls, puts = chain(e)
        except Exception:
            continue
        for side, df in (("call", calls), ("put", puts)):
            vol = df["volume"].fillna(0)
            oi = df["openInterest"].fillna(0)
            if side == "call":
                cv += vol.sum(); coi += oi.sum()
            else:
                pv += vol.sum(); poi += oi.sum()
            hot = df[(vol >= 500) & (vol > 2 * oi)]
            for r in hot.to_dict("records"):
                unusual.append({"expiry": e, "side": side, "strike": clean(r["strike"]), "volume": int(r["volume"] or 0),
                                "oi": int(r["openInterest"] or 0) if r["openInterest"] == r["openInterest"] else 0,
                                "iv": clean(r.get("impliedVolatility")), "last": clean(r.get("lastPrice"))})
    out["pcVolume"] = clean(pv / cv if cv else None)
    out["pcOI"] = clean(poi / coi if coi else None)
    out["volume"] = {"calls": int(cv), "puts": int(pv)}
    out["unusual"] = sorted(unusual, key=lambda u: -u["volume"])[:10]
    # one compact chain around the money for the chosen expiry
    e = expiry if expiry in exps else near
    try:
        calls, puts = chain(e)
        strikes = sorted(set(calls["strike"]) | set(puts["strike"]))
        if price:
            strikes = sorted(strikes, key=lambda s: abs(s - price))[:14]
            strikes.sort()
        C = {r["strike"]: r for r in calls.to_dict("records")}
        P = {r["strike"]: r for r in puts.to_dict("records")}
        pick = lambda r: None if r is None else {"bid": clean(r.get("bid")), "ask": clean(r.get("ask")), "last": clean(r.get("lastPrice")),
                                                 "vol": clean(r.get("volume")), "oi": clean(r.get("openInterest")), "iv": clean(r.get("impliedVolatility"))}
        out["chain"] = {"expiry": e, "rows": [{"strike": clean(k), "call": pick(C.get(k)), "put": pick(P.get(k))} for k in strikes]}
    except Exception:
        out["chain"] = None
    return out


# ---------------------------------------------------------------- dividends, splits, filings
def events(sym):
    t = yf.Ticker(sym)
    out = {"t": sym}
    try:
        dv = t.dividends
        out["dividends"] = [{"date": iso(i), "amount": clean(v)} for i, v in dv.items()][-40:]
        by_year = {}
        for i, v in dv.items():
            by_year[pd.Timestamp(i).year] = by_year.get(pd.Timestamp(i).year, 0) + float(v)
        out["dividendYears"] = [{"year": y, "total": round(v, 4)} for y, v in sorted(by_year.items())][-12:]
    except Exception:
        out["dividends"], out["dividendYears"] = [], []
    try:
        out["splits"] = [{"date": iso(i), "ratio": clean(v)} for i, v in t.splits.items()]
    except Exception:
        out["splits"] = []
    try:
        fl = t.sec_filings or []
        out["filings"] = [{"date": clean(f.get("date")), "type": f.get("type"), "title": f.get("title"),
                           "url": f.get("edgarUrl") or (list((f.get("exhibits") or {}).values()) or [None])[0]}
                          for f in fl[:80]]
    except Exception:
        out["filings"] = []
    return out


# ---------------------------------------------------------------- ETFs
def etf(sym):
    fd = yf.Ticker(sym).funds_data
    out = {"t": sym}
    try:
        th = fd.top_holdings
        out["holdings"] = [{"t": str(i), "n": r.get("Name"), "w": clean(r.get("Holding Percent"))} for i, r in zip(th.index, th.to_dict("records"))]
    except Exception:
        out["holdings"] = []
    for key, attr in (("sectors", "sector_weightings"), ("assets", "asset_classes"), ("overview", "fund_overview")):
        try:
            out[key] = clean(getattr(fd, attr) or {})
        except Exception:
            out[key] = {}
    try:
        ops = fd.fund_operations
        out["operations"] = {str(i): {"fund": clean(r.iloc[0]), "category": clean(r.iloc[1])} for i, r in ops.iterrows()}
    except Exception:
        out["operations"] = {}
    try:
        out["description"] = fd.description
    except Exception:
        pass
    return _need(out, "holdings", "sectors", "operations")


# ---------------------------------------------------------------- market
MACRO = [
    ("^GSPC", "S&P 500", "index"), ("^IXIC", "Nasdaq", "index"), ("^DJI", "Dow Jones", "index"), ("^RUT", "Russell 2000", "index"),
    ("^VIX", "VIX (fear gauge)", "vol"), ("^TNX", "10-year yield", "rate"), ("^FVX", "5-year yield", "rate"), ("^IRX", "3-month T-bill", "rate"),
    ("DX-Y.NYB", "US dollar index", "fx"), ("CL=F", "Crude oil", "commodity"), ("GC=F", "Gold", "commodity"),
    ("BTC-USD", "Bitcoin", "crypto"), ("ES=F", "S&P futures", "future"), ("NQ=F", "Nasdaq futures", "future"),
]
SECTOR_ETFS = [
    ("XLK", "Technology", "technology"), ("XLC", "Communication", "communication-services"),
    ("XLY", "Consumer discretionary", "consumer-cyclical"), ("XLP", "Consumer staples", "consumer-defensive"),
    ("XLF", "Financials", "financial-services"), ("XLV", "Health care", "healthcare"), ("XLI", "Industrials", "industrials"),
    ("XLE", "Energy", "energy"), ("XLB", "Materials", "basic-materials"), ("XLU", "Utilities", "utilities"),
    ("XLRE", "Real estate", "real-estate"),
]


def _series(syms, period="1y", interval="1d"):
    df = yf.download(syms, period=period, interval=interval, auto_adjust=False, progress=False, threads=True, group_by="column")
    close = df["Close"] if "Close" in df else df
    if isinstance(close, pd.Series):
        close = close.to_frame(syms[0])
    return close


def macro_daily():
    syms = [m[0] for m in MACRO] + [s[0] for s in SECTOR_ETFS]
    raw = _series(syms, "13mo", "1d")
    # fill holes inside a series only: Yahoo often leaves today's daily bar empty for a while after the close,
    # and a trailing fill would copy yesterday into today and make every daily change read 0.00%
    close = raw.ffill().where(raw.bfill().notna())
    dates = [d.strftime("%Y-%m-%d") for d in close.index]
    px = {c: [clean(round(float(v), 4)) if v == v else None for v in close[c].tolist()] for c in close.columns}
    return {"dates": dates, "px": px}


def macro_intraday():
    syms = [m[0] for m in MACRO] + [s[0] for s in SECTOR_ETFS]
    close = _series(syms, "1d", "5m")
    last, spark = {}, {}
    for c in close.columns:
        s = close[c].dropna()
        if len(s):
            last[c] = clean(float(s.iloc[-1]))
            spark[c] = [clean(round(float(v), 4)) for v in s.tolist()]
    return {"last": last, "spark": spark}


def market_status():
    try:
        st = yf.Market("US").status or {}
        return {"status": st.get("status"), "message": st.get("message"), "open": clean(st.get("open")), "close": clean(st.get("close"))}
    except Exception:
        return {}


def sector_detail(key):
    s = yf.Sector(key)
    out = {"key": key}
    try:
        out["overview"] = clean(s.overview or {})
    except Exception:
        out["overview"] = {}
    try:
        ind = s.industries
        out["industries"] = [{"key": str(i), "name": r.get("name"), "weight": clean(r.get("market weight"))} for i, r in zip(ind.index, ind.to_dict("records"))]
    except Exception:
        out["industries"] = []
    try:
        tc = s.top_companies
        out["companies"] = [{"t": str(i).replace(".", "-"), "n": r.get("name"), "rating": r.get("rating"), "weight": clean(r.get("market weight"))}
                            for i, r in zip(tc.index, tc.to_dict("records"))][:25]
    except Exception:
        out["companies"] = []
    return _need(out, "overview", "industries", "companies")


def industry_detail(key):
    s = yf.Industry(key)
    out = {"key": key}
    try:
        out["overview"] = clean(s.overview or {})
    except Exception:
        out["overview"] = {}
    for k, attr in (("top", "top_companies"), ("performers", "top_performing_companies"), ("growth", "top_growth_companies")):
        try:
            df = getattr(s, attr)
            out[k] = [{"t": str(i).replace(".", "-"), **{str(c): clean(v) for c, v in r.items()}} for i, r in zip(df.index, df.to_dict("records"))][:15]
        except Exception:
            out[k] = []
    return _need(out, "top", "performers", "growth")


# ---------------------------------------------------------------- screeners
QUOTE_FIELDS = ["symbol", "shortName", "longName", "regularMarketPrice", "regularMarketChangePercent", "regularMarketVolume",
                "averageDailyVolume3Month", "marketCap", "trailingPE", "forwardPE", "fiftyTwoWeekChangePercent",
                "dividendYield", "epsTrailingTwelveMonths", "averageAnalystRating", "quoteType", "exchange", "fullExchangeName"]

SCREEN_NAMES = {
    "day_gainers": "Biggest gainers today", "day_losers": "Biggest losers today", "most_actives": "Most active today",
    "undervalued_growth_stocks": "Undervalued growth", "undervalued_large_caps": "Undervalued large caps",
    "growth_technology_stocks": "Growth tech", "aggressive_small_caps": "Aggressive small caps",
    "small_cap_gainers": "Small-cap gainers", "most_shorted_stocks": "Most shorted",
    "portfolio_anchors": "Portfolio anchors (funds)", "solid_large_growth_funds": "Large growth funds",
    "solid_midcap_growth_funds": "Mid-cap growth funds", "top_mutual_funds": "Top mutual funds",
    "conservative_foreign_funds": "Conservative foreign funds", "high_yield_bond": "High-yield bond funds",
}


def _quotes(res):
    out = []
    for q in (res or {}).get("quotes", []):
        sym = str(q.get("symbol") or "")
        out.append({k: clean(q.get(k)) for k in QUOTE_FIELDS} | {"t": sym.replace(".", "-")})
    return out


def screen_predefined(name, count=50):
    if name not in yf.PREDEFINED_SCREENER_QUERIES:
        raise ValueError("unknown screen")
    return _quotes(yf.screen(name, count=count))


def screen_list():
    names = list(yf.PREDEFINED_SCREENER_QUERIES)
    return [{"key": n, "name": SCREEN_NAMES.get(n, n.replace("_", " ").capitalize())} for n in names]


SORT_FIELDS = {"marketcap": "intradaymarketcap", "change": "percentchange", "pe": "peratio.lasttwelvemonths",
               "growth": "quarterlyrevenuegrowth.quarterly", "yield": "forward_dividend_yield", "year": "fiftytwowkpercentchange"}


def screen_custom(p: dict, count=50):
    EQ = yf.EquityQuery
    parts = [EQ("eq", ["region", "us"]),
             EQ("is-in", ["exchange", "NMS", "NYQ", "NGM", "NCM", "ASE"])]   # US exchanges, no OTC or ADR pink sheets
    num = lambda k: (float(p[k]) if p.get(k) not in (None, "") else None)
    if num("capMin") is not None:
        parts.append(EQ("gte", ["intradaymarketcap", num("capMin") * 1e9]))
    if num("capMax") is not None:
        parts.append(EQ("lte", ["intradaymarketcap", num("capMax") * 1e9]))
    if num("peMax") is not None:
        parts.append(EQ("btwn", ["peratio.lasttwelvemonths", 0, num("peMax")]))
    if num("growthMin") is not None:
        parts.append(EQ("gte", ["quarterlyrevenuegrowth.quarterly", num("growthMin")]))
    if num("yieldMin") is not None:
        parts.append(EQ("gte", ["forward_dividend_yield", num("yieldMin")]))
    if num("yearMin") is not None:
        parts.append(EQ("gte", ["fiftytwowkpercentchange", num("yearMin")]))
    if num("yearMax") is not None:
        parts.append(EQ("lte", ["fiftytwowkpercentchange", num("yearMax")]))
    if p.get("sector"):
        parts.append(EQ("eq", ["sector", str(p["sector"])]))
    q = EQ("and", parts)
    sort = SORT_FIELDS.get(p.get("sort") or "marketcap", "intradaymarketcap")
    return _quotes(yf.screen(q, size=count, sortField=sort, sortAsc=bool(p.get("asc"))))


# ---------------------------------------------------------------- calendars
def _cal(days_back=2, days_ahead=14):
    today = dt.date.today()
    return yf.Calendars(start=today - dt.timedelta(days=days_back), end=today + dt.timedelta(days=days_ahead))


def economic_calendar():
    c = _cal(3, 14)
    rows = []
    for off in range(0, 1000, 100):
        df = c.get_economic_events_calendar(limit=100, offset=off)
        if df is None or df.empty:
            break
        for name, r in zip(df.index, df.to_dict("records")):
            if str(r.get("Region") or "").upper() not in ("US", "UNITED STATES"):
                continue
            ts = r.get("Event Time")
            try:
                ts = pd.Timestamp(ts).tz_convert(NY)
            except Exception:
                try:
                    ts = pd.Timestamp(ts).tz_localize("UTC").tz_convert(NY)
                except Exception:
                    continue
            rows.append({"event": str(name).rstrip("*"), "date": ts.strftime("%Y-%m-%d"), "time": ts.strftime("%H:%M"),
                         "for": clean(r.get("For")), "actual": clean(r.get("Actual")), "expected": clean(r.get("Expected")),
                         "last": clean(r.get("Last")), "revised": clean(r.get("Revised"))})
        if len(df) < 100:
            break
        time.sleep(0.3)
    rows.sort(key=lambda r: (r["date"], r["time"]))
    return rows


def ipo_calendar():
    df = _cal(7, 30).get_ipo_info_calendar(limit=100)
    out = []
    if df is None or df.empty:
        return out
    for sym, r in zip(df.index, df.to_dict("records")):
        out.append({"t": str(sym), "company": r.get("Company"), "exchange": r.get("Exchange"), "date": iso(r.get("Date")),
                    "filed": iso(r.get("Filing Date")), "priceFrom": clean(r.get("Price From")), "priceTo": clean(r.get("Price To")),
                    "price": clean(r.get("Price")), "shares": clean(r.get("Shares")), "action": r.get("Action")})
    out.sort(key=lambda r: r["date"] or "")
    return out


def splits_calendar():
    df = _cal(7, 30).get_splits_calendar(limit=100)
    out = []
    if df is None or df.empty:
        return out
    for sym, r in zip(df.index, df.to_dict("records")):
        s = str(sym)
        if "." in s:      # US listings only
            continue
        out.append({"t": s, "company": r.get("Company"), "date": iso(r.get("Payable On")),
                    "old": clean(r.get("Old Share Worth")), "new": clean(r.get("Share Worth")), "optionable": r.get("Optionable")})
    out.sort(key=lambda r: r["date"] or "")
    return out
