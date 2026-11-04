"""OpenTicker: live market dashboard with research, alerts and an AI agent layer.

Serves a local web page that shows, for SPY, QQQ, SMH and SPSM, how each
holding is performing against the fund over a chosen horizon and how much it
contributed to the fund's return (start weight x return).

Data:
  * Holdings and weights: the fund issuers' daily holdings files
    (State Street for SPY and SPSM, Invesco for QQQ, VanEck for SMH). A fund
    without a full file (iShares blocks scripted downloads) uses Yahoo's top-10
    holdings and the rest of the fund shows as one "Other holdings" line.
  * Daily price history: Yahoo Finance via yfinance (split/dividend adjusted).
  * Live prices: Yahoo's streaming quote feed via yfinance.WebSocket, with a
    polling fallback if the stream goes quiet.

Run:  ./run.sh   (or: python server.py --port 8765)
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import re
import os
import subprocess
import sys
import threading
import time
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

import agent  # noqa: E402
import paths  # noqa: E402
import personal  # noqa: E402
import yahoo_extra as X  # noqa: E402

warnings.filterwarnings("ignore")   # yfinance resets filters on import; keep pandas deprecation noise out of the log

HERE = Path(__file__).resolve().parent
CACHE = paths.CACHE
NY = ZoneInfo("America/New_York")

# The funds on the Funds page. To add one, add it here and to FUND_LIST in app/index.html. Its holdings come from
# HOLDING_SOURCES below when the issuer publishes a full file, otherwise from Yahoo's top holdings (holdings_yahoo).
FUNDS = {
    "SPY": "SPDR S&P 500 ETF",
    "QQQ": "Invesco QQQ (Nasdaq-100)",
    "SMH": "VanEck Semiconductor ETF",
    "SPSM": "SPDR S&P 600 Small Cap ETF",
}

HOLDINGS_TTL = 12 * 3600      # refetch issuer files twice a day
HISTORY_TTL = 30 * 60         # refresh daily bars every 30 minutes
HISTORY_CACHE = CACHE / "history.json"
POLL_FALLBACK = 60            # poll prices if the stream is quiet this long


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def curl(url: str, jar: str | None = None) -> bytes:
    cmd = ["curl", "-sSL", "-m", "60"]
    if jar:  # some issuer sites set a session cookie on the first page view
        cmd += ["-c", jar, "-b", jar]
    out = subprocess.run(cmd + [url], capture_output=True, check=True)
    return out.stdout


def yahoo_symbol(t: str) -> str:
    return t.strip().upper().replace(".", "-").replace("/", "-").replace(" ", "-")


VALID = re.compile(r"[A-Z]{1,5}(-[A-Z]{1,2})?")


def clean(rows):
    """Drop cash lines, futures and identifiers that are not exchange tickers."""
    return [r for r in rows if VALID.fullmatch(r["t"])]


def download_closes(syms, **kw):
    """yf.download in modest batches with retries; Yahoo times out on big bursts."""
    frames, todo = [], list(syms)
    for attempt in range(3):
        missing = []
        size = 60 if attempt == 0 else 20
        for i in range(0, len(todo), size):
            batch = todo[i:i + size]
            try:
                df = yf.download(batch, auto_adjust=True, progress=False, threads=4,
                                 group_by="column", **kw)["Close"]
                if isinstance(df, pd.Series):
                    df = df.to_frame(batch[0])
                good = [c for c in df.columns if df[c].notna().any()]
                frames.append(df[good])
                missing += [b for b in batch if b not in good]
            except Exception as e:
                log(f"batch failed: {e!r}")
                missing += batch
        todo = missing
        if not todo:
            break
        time.sleep(3)
    if todo:
        log(f"no prices for {len(todo)} symbols: {todo[:30]}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).sort_index()


# ---------------------------------------------------------------- holdings
def holdings_ssga(fund):
    """Any SPDR fund: State Street's daily holdings file."""
    raw = curl("https://www.ssga.com/us/en/intermediary/library-content/products/"
               f"fund-data/etfs/us/holdings-daily-us-en-{fund.lower()}.xlsx")
    head = pd.read_excel(io.BytesIO(raw), header=None, nrows=4)
    as_of = str(head.iloc[2, 1]).replace("As of ", "")
    df = pd.read_excel(io.BytesIO(raw), header=4)
    df = df[df["Ticker"].notna() & df["Weight"].notna()]
    rows = [{"t": yahoo_symbol(str(t)), "n": str(n).title(), "w": float(w)}
            for t, n, w in zip(df["Ticker"].tolist(), df["Name"].tolist(), df["Weight"].tolist())
            if str(t).strip() not in ("-", "", "nan") and float(w) > 0]
    return rows, as_of, True


def holdings_qqq():
    raw = curl("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/"
               "holdings/fund?idType=ticker&productType=ETF")
    j = json.loads(raw)
    rows = [{"t": yahoo_symbol(h["ticker"]), "n": h.get("issuerName", h["ticker"]),
             "w": float(h["percentageOfTotalNetAssets"])}
            for h in j["holdings"]
            if h.get("ticker") and any(k in (h.get("securityTypeName") or "")
                                       for k in ("Common", "Depository", "Depositary"))]
    return rows, j.get("effectiveBusinessDate", ""), True


def holdings_smh():
    jar = str(CACHE / "vaneck.cookies")
    curl("https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/", jar)
    raw = curl("https://www.vaneck.com/us/en/etf/equity/smh/holdings/download/xlsx/", jar)
    head = " ".join(map(str, pd.read_excel(io.BytesIO(raw), header=None).head(2).values.ravel()))
    m = re.search(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", head)
    as_of = m.group(0) if m else ""
    df = pd.read_excel(io.BytesIO(raw), header=2)
    df = df[df["Asset Class"].astype(str).str.strip().eq("Stock")]
    rows = []
    for t, n, w in zip(df["Ticker"].tolist(), df["Holding Name"].tolist(), df["% of Net Assets"].tolist()):
        rows.append({"t": yahoo_symbol(str(t)), "n": str(n),
                     "w": float(str(w).replace("%", "").replace(",", ""))})
    return rows, as_of, True


def holdings_yahoo(fund):
    """Any ETF: Yahoo's top holdings (usually ten). The rest of the fund shows as one 'Other' line."""
    th = yf.Ticker(fund).funds_data.top_holdings
    rows = [{"t": yahoo_symbol(sym), "n": str(r["Name"]), "w": float(r["Holding Percent"]) * 100}
            for sym, r in th.iterrows()]
    return rows, "Yahoo top 10", False


# Full holdings files from the issuers. A fund that isn't listed here uses holdings_yahoo.
HOLDING_SOURCES = {"SPY": lambda: holdings_ssga("SPY"), "SPSM": lambda: holdings_ssga("SPSM"),
                   "QQQ": holdings_qqq, "SMH": holdings_smh}


def load_holdings(force=False):
    path = CACHE / "holdings.json"
    old = {}
    if path.exists():
        old = json.loads(path.read_text())
        if not force and time.time() - old.get("_fetched", 0) < HOLDINGS_TTL and all(f in old for f in FUNDS):
            return old
    out = {"_fetched": time.time()}
    for fund in FUNDS:
        try:
            fn = HOLDING_SOURCES.get(fund)
            rows, as_of, complete = fn() if fn else holdings_yahoo(fund)
            rows = clean(rows)
            if not rows:
                raise ValueError("no rows")
            out[fund] = {"name": FUNDS[fund], "asOf": as_of, "complete": complete, "holdings": rows}
            log(f"holdings {fund}: {len(rows)} names, {sum(r['w'] for r in rows):.1f}% of fund, as of {as_of}")
            health(f"holdings {fund}")
        except Exception as e:  # keep yesterday's file rather than nothing
            log(f"holdings {fund} failed: {e!r}")
            health(f"holdings {fund}", False, e)
            if fund in old:
                out[fund] = old[fund]
    path.write_text(json.dumps(out))
    return out


# ---------------------------------------------------------------- sectors
SECTORS_PATH = CACHE / "sectors.json"


def load_sectors():
    return json.loads(SECTORS_PATH.read_text()) if SECTORS_PATH.exists() else {}


def sector_loop():
    """Fill in GICS-style sectors from Yahoo once per symbol, slowly, and cache them."""
    time.sleep(5)
    while True:
        known = load_sectors()
        todo = [t for t in S.tickers() if t not in FUNDS and t not in known]
        if todo:
            log(f"looking up sectors for {len(todo)} symbols")
        added = 0
        for t in todo:
            try:
                info = yf.Ticker(t).get_info()
                known[t] = info.get("sector") or info.get("quoteType", "Other").title()
                added += 1
            except Exception as e:
                log(f"sector {t} failed: {e!r}")
                time.sleep(5)
            time.sleep(0.25)
            if added and added % 50 == 0:
                SECTORS_PATH.write_text(json.dumps(known))
                with S.lock:
                    S.sectors = dict(known)
                    S.version += 1
        if added:
            SECTORS_PATH.write_text(json.dumps(known))
            with S.lock:
                S.sectors = dict(known)
                S.version += 1
            log(f"sectors ready for {len(known)} symbols")
        time.sleep(6 * 3600)


# ---------------------------------------------------------------- state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.holdings = {}
        self.dates: list[str] = []
        self.px: dict[str, list] = {}
        self.version = 0
        self.last_tick = 0.0          # wall time of the last streamed regular-hours tick
        self.ticks = 0
        self.last_poll = 0.0
        self.history_fetched = 0.0
        self.boot = "Starting up"   # what the first launch is doing, shown on the loading screen
        self.stream_status = "starting"
        self.sectors = load_sectors()
        self.extras: list[str] = []   # tickers opened from search that aren't in any fund

    def tickers(self):
        s = set(FUNDS) | set(self.extras) | set(personal.all_symbols())
        for f in FUNDS:
            for h in self.holdings.get(f, {}).get("holdings", []):
                s.add(h["t"])
        return sorted(s)

    def track(self, sym):
        """Add a searched ticker: fetch its daily closes on the same calendar as everything else."""
        return sym in self.track_many([sym])

    def track_many(self, syms):
        """track() for several tickers in one download. Returns the ones that now have prices."""
        with self.lock:
            have = {s for s in syms if s in self.px}
            dates = list(self.dates)
        todo = [s for s in dict.fromkeys(syms) if s not in have]
        if not todo or not dates:
            return have
        df = download_closes(todo, start=(dt.date.fromisoformat(dates[0]) - dt.timedelta(days=5)).isoformat())
        got = {}
        for sym in todo:
            if df.empty or sym not in df.columns:
                continue
            col = df[sym].copy()
            col.index = [d.strftime("%Y-%m-%d") for d in col.index]
            col = col[~col.index.duplicated()].reindex(dates)
            arr = [None if v != v else round(float(v), 4) for v in col.tolist()]
            if any(v is not None for v in arr):
                got[sym] = arr
        if not got:
            return have
        with self.lock:
            for sym, arr in got.items():
                if len(self.dates) != len(dates):   # a new session row opened meanwhile
                    arr += [arr[-1]] * (len(self.dates) - len(dates))
                self.px[sym] = arr
                if sym not in self.extras and sym not in personal.all_symbols():
                    self.extras = (self.extras + [sym])[-60:]
            self.version += 1
        try:  # stream live ticks for them too
            if getattr(self, "ws", None):
                self.ws.subscribe(list(got))
        except Exception:
            pass
        return have | set(got)

    # daily bars ---------------------------------------------------------
    def load_history(self):
        syms = self.tickers()
        start = dt.date(dt.date.today().year - 1, 1, 1) - dt.timedelta(days=10)
        log(f"downloading daily history for {len(syms)} symbols since {start}")
        df = download_closes(syms, start=start.isoformat())
        df = df.loc[:, ~df.columns.duplicated()].dropna(how="all").sort_index()
        dates = [d.strftime("%Y-%m-%d") for d in df.index]
        px = {}
        for c in df.columns:
            col = df[c].tolist()
            px[c] = [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), 4)
                     for v in col]
        # Yahoo's daily download sometimes leaves the latest session empty (it did on the evening of 2026-11-03),
        # which would quietly roll every "today" number back a day. Fill the session from minute bars instead.
        now_ny = dt.datetime.now(NY)
        session = now_ny.strftime("%Y-%m-%d") if now_ny.weekday() < 5 and now_ny.time() >= dt.time(9, 30) else None
        if session and dates and dates[-1] < session:
            try:
                m = download_closes(syms, period="1d", interval="1m")
                day = pd.Timestamp(m.index[-1]).tz_convert(NY).strftime("%Y-%m-%d") if len(m.index) else None
                if day == session:
                    last = m.ffill().iloc[-1]
                    dates.append(day)
                    for t in px:
                        v = last.get(t)
                        px[t].append(round(float(v), 4) if v is not None and v == v else None)
                    log(f"filled {day} from minute bars ({int(last.notna().sum())} symbols); the daily download didn't have it yet")
            except Exception as e:
                log(f"couldn't fill {session} from minute bars: {e!r}")
        with self.lock:
            # never go backwards: if the download is behind what we already had, keep our newer session
            if self.dates and dates and self.dates[-1] > dates[-1] and self.dates[-2:-1] == dates[-1:]:
                dates.append(self.dates[-1])
                for t in px:
                    old = self.px.get(t)
                    px[t].append(old[-1] if old else None)
            # keep any streamed price for today that is newer than the download
            if self.dates and dates and self.dates[-1] == dates[-1]:
                for t, arr in self.px.items():
                    if t in px and arr and arr[-1] is not None and self.last_tick > time.time() - 120:
                        px[t][-1] = arr[-1]
            self.dates, self.px = dates, px
            self.history_fetched = time.time()
            self.version += 1
        self.save_cache()
        missing = [s for s in syms if s not in px or all(v is None for v in px[s])]
        log(f"history ready: {len(dates)} days through {dates[-1] if dates else '?'}; "
            f"{len(syms) - len(missing)}/{len(syms)} symbols priced")

    # a copy on disk, so the next start shows the dashboard at once and refreshes behind it
    def save_cache(self):
        try:
            with self.lock:
                blob = json.dumps({"dates": self.dates, "px": self.px, "fetched": self.history_fetched}, separators=(",", ":"))
            tmp = HISTORY_CACHE.with_suffix(".tmp")
            tmp.write_text(blob)
            tmp.replace(HISTORY_CACHE)
        except Exception as e:
            log(f"couldn't save the price cache: {e!r}")

    def load_cache(self):
        """Holdings and daily history from the last run, at any age. True when there's enough to show the dashboard."""
        try:
            hold = json.loads((CACHE / "holdings.json").read_text())
            hist = json.loads(HISTORY_CACHE.read_text())
        except Exception:
            return False
        if not hist.get("dates") or not any(f in hold for f in FUNDS):
            return False
        with self.lock:
            self.holdings = {k: v for k, v in hold.items() if k in FUNDS}
            self.dates, self.px = hist["dates"], hist["px"]
            self.history_fetched = hist.get("fetched") or 0.0
            self.version += 1
        log(f"showing the last run's prices ({len(self.dates)} days through {self.dates[-1]}) while fresh ones download")
        return True

    # live prices ---------------------------------------------------------
    def apply_price(self, sym, price, day):
        with self.lock:
            if not self.dates or sym not in self.px or price is None:
                return
            if day > self.dates[-1]:
                # first regular-hours tick of a new session: open a new row
                self.dates.append(day)
                for arr in self.px.values():
                    arr.append(arr[-1] if arr else None)
                self.version += 1
            if day == self.dates[-1]:
                self.px[sym][-1] = round(float(price), 4)

    def snapshot_live(self):
        with self.lock:
            return {
                "v": self.version,
                "date": self.dates[-1] if self.dates else None,
                "last": {t: a[-1] for t, a in self.px.items() if a},
                "lastTick": self.last_tick,
                "ticks": self.ticks,
                "stream": self.stream_status,
                "lastPoll": self.last_poll,
                "now": time.time(),
            }

    def snapshot_base(self):
        with self.lock:
            return {
                "v": self.version,
                "funds": {f: self.holdings[f] for f in FUNDS if f in self.holdings},
                "dates": self.dates,
                "px": self.px,
                "sectors": self.sectors,
                "extras": self.extras,
                "historyFetched": self.history_fetched,
            }


S = State()


def stream_loop():
    """Yahoo streaming quotes. Reconnects forever."""
    def on_msg(m):
        try:
            if m.get("market_hours") != 1:      # regular session only
                return
            ts = int(m.get("time", 0)) / 1000
            day = dt.datetime.fromtimestamp(ts, NY).strftime("%Y-%m-%d")
            S.apply_price(m["id"], m.get("price"), day)
            S.last_tick = time.time()
            S.ticks += 1
            S.stream_status = "live"
        except Exception:
            pass

    while True:
        try:
            syms = S.tickers()
            ws = yf.WebSocket(verbose=False)
            ws.subscribe(syms)
            S.ws = ws
            S.stream_status = "connected"
            log(f"stream subscribed to {len(syms)} symbols")
            ws.listen(on_msg)
        except Exception as e:
            S.stream_status = "reconnecting"
            log(f"stream dropped: {e!r}")
        time.sleep(5)


def poll_loop():
    """Fallback when the stream is quiet during market hours, plus periodic refreshes."""
    while True:
        time.sleep(15)
        try:
            now_ny = dt.datetime.now(NY)
            open_ = now_ny.weekday() < 5 and dt.time(9, 30) <= now_ny.time() <= dt.time(16, 5)
            if time.time() - S.history_fetched > HISTORY_TTL:
                old = S.holdings
                S.holdings = {k: v for k, v in load_holdings().items() if k in FUNDS} or old
                S.load_history()
                continue
            if open_ and time.time() - S.last_tick > POLL_FALLBACK and time.time() - S.last_poll > POLL_FALLBACK:
                syms = S.tickers()
                df = download_closes(syms, period="1d", interval="1m")
                day = now_ny.strftime("%Y-%m-%d")
                last = df.ffill().iloc[-1]
                for sym, v in last.items():
                    if v == v:
                        S.apply_price(sym, float(v), day)
                S.last_poll = time.time()
                if S.stream_status != "live":
                    S.stream_status = "polling"
                log("polled prices (stream quiet)")
        except Exception as e:
            log(f"poll failed: {e!r}")


# ---------------------------------------------------------------- per-stock detail
INFO_TTL = 6 * 3600
NEWS_TTL = 15 * 60
_detail_cache: dict = {}
_detail_lock = threading.Lock()

INFO_KEYS = [
    "longName", "shortName", "sector", "industry", "quoteType", "currency", "exchange",
    "marketCap", "enterpriseValue", "beta", "trailingPE", "forwardPE", "trailingPegRatio", "pegRatio",
    "priceToSalesTrailing12Months", "priceToBook", "enterpriseToEbitda", "trailingEps", "forwardEps",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth", "grossMargins", "operatingMargins",
    "profitMargins", "returnOnEquity", "freeCashflow", "totalRevenue", "debtToEquity",
    "dividendYield", "dividendRate", "heldPercentInstitutions", "shortPercentOfFloat",
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
    "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
    "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd", "isEarningsDateEstimate",
    "averageVolume", "averageVolume10days", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "currentPrice", "previousClose",
    "fullTimeEmployees", "city", "state", "country", "website", "longBusinessSummary",
]


# ---------------------------------------------------------------- data health: when each source last worked, and what failed
HEALTH: dict = {}               # source -> {"ok": time, "fail": time, "err": text}
_stale_keys: set = set()        # cache keys currently served from an old copy because the refresh failed


def health(name, ok=True, err=None):
    h = HEALTH.setdefault(name, {})
    h["ok" if ok else "fail"] = time.time()
    if not ok:
        h["err"] = str(err)[:200]


def _source(key):
    return f"{key[1]}" if key and key[0] == "x" else str(key[0])


def stale_age(key):
    """Seconds since the copy we're serving was fetched, if a refresh failed and we fell back to it; else None."""
    with _detail_lock:
        hit = _detail_cache.get(key)
        return time.time() - hit[0] if hit and key in _stale_keys else None


def cached(key, ttl, fn):
    """Small TTL cache. Yahoo fails now and then for a moment, so a failed fetch is tried once more; if it still
    fails we serve the last good copy, from memory or from the last run (cache/detail.json), when there is one."""
    now = time.time()
    with _detail_lock:
        hit = _detail_cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        try:
            val = fn()
        except Exception as e:
            log(f"{key} failed, trying once more: {e!r}")
            time.sleep(1.2)
            val = fn()
    except Exception as e:
        log(f"{key} failed: {e!r}")
        health(_source(key), False, e)
        if not hit:
            with _detail_lock:
                old = _disk_cache.get(_disk_key(key))
            if old:
                hit = (old[0], old[1])
                with _detail_lock:
                    _detail_cache.setdefault(key, hit)
        if hit:
            _stale_keys.add(key)
            return hit[1]
        raise
    with _detail_lock:
        _detail_cache[key] = (now, val)
        _stale_keys.discard(key)
    health(_source(key))
    return val


# ---------------------------------------------------------------- last good copies on disk, for when Yahoo fails after a restart
DETAIL_CACHE = CACHE / "detail.json"
DISK_KINDS = ("x", "info", "news", "chart")   # what the page shows; kept for a week
_disk_cache: dict = {}


def _disk_key(key):
    return json.dumps(key, default=str)


def load_disk_cache():
    global _disk_cache
    try:
        raw = json.loads(DETAIL_CACHE.read_text())
        _disk_cache = {k: (v[0], v[1]) for k, v in raw.items() if time.time() - v[0] < 7 * 86400}
        log(f"kept {len(_disk_cache)} research results from the last run as a fallback")
    except Exception:
        _disk_cache = {}


def save_disk_cache(last=None):
    """Write the research the page has shown, so a failed fetch after a restart still has a copy. Returns a
    signature so the loop can skip writing when nothing changed."""
    with _detail_lock:
        items = [(k, v) for k, v in _detail_cache.items() if k and k[0] in DISK_KINDS]
    out = dict(_disk_cache)
    for k, (ts, val) in items:
        out[_disk_key(k)] = (ts, jsonable(val))
    out = {k: v for k, v in out.items() if time.time() - v[0] < 7 * 86400}
    sig = (len(out), max((v[0] for v in out.values()), default=0))
    if sig != last:
        tmp = DETAIL_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, separators=(",", ":")))
        tmp.replace(DETAIL_CACHE)
    return sig


def disk_cache_loop():
    last = None
    while True:
        time.sleep(300)
        try:
            last = save_disk_cache(last)
        except Exception as e:
            log(f"couldn't save research cache: {e!r}")


def jsonable(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, (int, str, bool)):
        return v
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return str(v)


def fetch_info(sym):
    tk = yf.Ticker(sym)
    for attempt in range(3):  # Yahoo sometimes answers 401 until its cookie/crumb refreshes
        try:
            info = tk.get_info() or {}
        except Exception:
            info = {}
        if info.get("quoteType"):
            break
        time.sleep(1.5 * (attempt + 1))
    else:
        raise ValueError("empty info")
    out = {k: jsonable(info.get(k)) for k in INFO_KEYS if info.get(k) is not None}
    try:  # analyst estimates (EPS and revenue: average, low, high) for the next report
        cal = tk.calendar or {}
        out["calendar"] = {k: jsonable(v) for k, v in cal.items()}
    except Exception as e:
        log(f"calendar {sym} failed: {e!r}")
    return out


def _thumb(res):
    res = [r for r in (res or []) if r.get("url")]
    if not res:
        return None
    small = [r for r in res if (r.get("width") or 0) >= 100]
    return min(small or res, key=lambda r: r.get("width") or 1e9)["url"]


def _news_item(n):
    """Yahoo has two news shapes (Ticker.news and Search.news); normalise both."""
    c = n.get("content") if isinstance(n.get("content"), dict) else None
    if c:
        link = (c.get("clickThroughUrl") or {}).get("url") or (c.get("canonicalUrl") or {}).get("url")
        ts = c.get("pubDate") or c.get("displayTime")
        try:
            ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() if ts else None
        except Exception:
            ts = None
        return {"title": c.get("title"), "publisher": (c.get("provider") or {}).get("displayName"),
                "link": link, "time": ts, "summary": c.get("summary") or c.get("description") or None,
                "thumb": _thumb((c.get("thumbnail") or {}).get("resolutions"))}
    return {"title": n.get("title"), "publisher": n.get("publisher"), "link": n.get("link"),
            "time": n.get("providerPublishTime"), "summary": None, "related": n.get("relatedTickers") or [],
            "thumb": _thumb((n.get("thumbnail") or {}).get("resolutions"))}


def fetch_news(sym):
    items, errs = [], []
    try:
        items = [_news_item(n) for n in (yf.Ticker(sym).get_news(count=12) or [])]
    except Exception as e:
        errs.append(repr(e))
    if not any(i["title"] for i in items):
        try:  # Yahoo's search endpoint carries ticker news too, from a different host
            s = yf.Search(sym, news_count=12, max_results=1, enable_fuzzy_query=False)
            items = [_news_item(n) for n in (s.news or [])]
            # search results mix in general market stories; keep the ones tagged with this ticker
            mine = [i for i in items if sym in i.get("related", [])]
            items = mine if len(mine) >= 3 else items
        except Exception as e:
            errs.append(repr(e))
    seen, out = set(), []
    for i in items:
        if not i["title"] or not str(i["link"] or "").startswith("http") or i["title"] in seen:
            continue
        seen.add(i["title"])
        i.pop("related", None)
        out.append(i)
    out.sort(key=lambda i: i["time"] or 0, reverse=True)
    if not out and errs:
        raise RuntimeError("; ".join(errs))
    return out[:12]


def stock_detail(sym):
    sym = yahoo_symbol(sym)
    out = {"t": sym}
    try:
        out["info"] = cached(("info", sym), INFO_TTL, lambda: fetch_info(sym))
    except Exception:
        out["info"], out["infoError"] = {}, "Yahoo Finance isn't answering right now. OpenTicker will try again shortly."
    try:
        out["news"] = cached(("news", sym), NEWS_TTL, lambda: fetch_news(sym))
    except Exception:
        out["news"], out["newsError"] = [], "Yahoo's news feed isn't answering right now. OpenTicker will try again shortly."
    return out


def search_tickers(q):
    def run():
        s = yf.Search(q, max_results=8, news_count=0, enable_fuzzy_query=True)
        out = []
        for r in s.quotes or []:
            if r.get("quoteType") not in ("EQUITY", "ETF") or not r.get("symbol") or "." in r["symbol"]:
                continue
            sym = yahoo_symbol(r["symbol"])
            if not VALID.fullmatch(sym):   # US listings only; prices come from the same feed
                continue
            out.append({"t": sym, "n": r.get("longname") or r.get("shortname") or sym,
                        "type": r.get("quoteType"), "exch": r.get("exchDisp") or r.get("exchange")})
        return out
    return cached(("search", q.lower()), 3600, run)


# range -> (period, interval): intraday bars for 1D/5D, daily up to 1Y, weekly for 5Y
CHART_RANGES = {
    "1D": ("1d", "5m"), "5D": ("5d", "30m"), "1M": ("1mo", "1d"), "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"), "YTD": ("ytd", "1d"), "1Y": ("1y", "1d"), "5Y": ("5y", "1wk"),
}


MA_DAYS = (50, 200)   # the moving averages drawn on daily charts
RANGE_START = {"1M": {"months": 1}, "3M": {"months": 3}, "6M": {"months": 6}, "1Y": {"years": 1}}


def fetch_chart(sym, rng):
    period, interval = CHART_RANGES[rng]
    tk = yf.Ticker(sym)
    ma = None
    if interval == "1d":
        # two years of bars so the 200-day average exists from the first day shown, then trim to the range
        h = tk.history(period="2y", interval="1d", auto_adjust=True, prepost=False).dropna(subset=["Close"])
        avgs = {n: h["Close"].rolling(n).mean() for n in MA_DAYS}
        last = h.index[-1] if len(h.index) else pd.Timestamp.now(tz=NY)
        start = (pd.Timestamp(year=last.year, month=1, day=1, tz=last.tz) if rng == "YTD"
                 else last.normalize() - pd.DateOffset(**RANGE_START[rng]))
        keep = h.index >= start
        h = h[keep]
        ma = {str(n): [None if v != v else round(float(v), 4) for v in a[keep].tolist()] for n, a in avgs.items()}
    else:
        h = tk.history(period=period, interval=interval, auto_adjust=True, prepost=False).dropna(subset=["Close"])
    pts = [[int(ts.timestamp()), round(float(c), 4), int(v) if v == v else 0]
           for ts, c, v in zip(h.index, h["Close"].tolist(), h["Volume"].tolist())]
    prev = None
    if rng == "1D":
        md = tk.history_metadata or {}
        prev = md.get("chartPreviousClose") or md.get("previousClose")
    if not pts:
        raise ValueError("no bars")
    return {"pts": pts, "intraday": interval.endswith("m"), "interval": interval, "prevClose": jsonable(prev), "ma": ma}


def market_open():
    now_ny = dt.datetime.now(NY)
    return now_ny.weekday() < 5 and dt.time(9, 30) <= now_ny.time() <= dt.time(16, 5)


def chart_ttl(rng):
    if rng in ("1D", "5D"):
        return 60 if market_open() else 30 * 60
    return 30 * 60


def stock_chart(sym, rng, vs=None):
    sym = yahoo_symbol(sym)
    rng = rng if rng in CHART_RANGES else "1M"
    out = {"t": sym, "range": rng, **cached(("chart", sym, rng), chart_ttl(rng), lambda: fetch_chart(sym, rng))}
    if vs in FUNDS and vs != sym:
        try:
            f = cached(("chart", vs, rng), chart_ttl(rng), lambda: fetch_chart(vs, rng))
            out["vs"] = {"t": vs, "pts": [p[:2] for p in f["pts"]], "prevClose": f.get("prevClose")}
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- earnings calendar
EARN_PATH = CACHE / "earnings.json"
EARN = json.loads(EARN_PATH.read_text()) if EARN_PATH.exists() else {}


def fetch_earnings_calendar():
    """Yahoo's earnings calendar, a week back to two weeks ahead, companies over $2B."""
    today = dt.date.today()
    cal = yf.Calendars(start=today - dt.timedelta(days=7), end=today + dt.timedelta(days=15))
    out = {}
    for off in range(0, 3000, 100):
        df = cal.get_earnings_calendar(market_cap=2e9, filter_most_active=False, limit=100, offset=off)
        if df is None or df.empty:
            break
        for sym, row in zip(df.index.tolist(), df.to_dict("records")):
            t = yahoo_symbol(str(sym))
            ts = row.get("Event Start Date")
            try:
                ts = pd.Timestamp(ts).tz_convert(NY)
            except Exception:
                continue
            item = {"date": ts.strftime("%Y-%m-%d"), "timing": (row.get("Timing") or "").strip() or None,
                    "epsEst": jsonable(row.get("EPS Estimate")), "reported": jsonable(row.get("Reported EPS")),
                    "surprise": jsonable(row.get("Surprise(%)")), "event": jsonable(row.get("Event Name"))}
            # keep the upcoming report if a ticker appears twice
            if t not in out or (out[t]["reported"] is not None and item["reported"] is None):
                out[t] = item
        if len(df) < 100:
            break
        time.sleep(0.5)
    return out


def ticker_earnings(sym):
    """One company's next (or just-passed) report from its own Yahoo page. Yahoo's calendar listing misses some
    companies (AMD on its report day, for one), so this fills the gaps for stocks people actually look at."""
    def run():
        c = yf.Ticker(sym).calendar or {}
        days = c.get("Earnings Date") or []
        if not days:
            raise ValueError("no earnings date")
        d = days[0].isoformat() if hasattr(days[0], "isoformat") else str(days[0])
        return {"date": d[:10], "timing": None, "epsEst": jsonable(c.get("Earnings Average")),
                "revEst": jsonable(c.get("Revenue Average")), "reported": None, "surprise": None, "event": None, "src": "company"}
    return cached(("ecal", sym), 12 * 3600, run)


def earnings_info(sym, fetch=True):
    """The calendar entry for a stock, falling back to the company's own page when the calendar has no row."""
    e = EARN.get(sym)
    if e or not fetch:
        return e or {}
    try:
        return ticker_earnings(sym)
    except Exception:
        return {}


def _earnings_watch_list():
    syms = set()
    for uid in personal.users():
        snap = personal.snapshot(uid)
        syms |= set(snap["watch"]) | {p["t"] for p in snap["positions"]}
    for f in FUNDS:        # the biggest names in each fund, since they drive the Market and Funds pages
        hs = sorted((S.holdings.get(f) or {}).get("holdings", []), key=lambda h: -h["w"])[:15]
        syms |= {h["t"] for h in hs}
    return sorted(syms)


def earnings_loop():
    global EARN
    time.sleep(20)
    while True:
        try:
            got = fetch_earnings_calendar()
            if got:
                filled = 0
                for t in _earnings_watch_list():
                    if t in got:
                        continue
                    try:
                        got[t] = ticker_earnings(t)
                        filled += 1
                    except Exception:
                        pass
                    time.sleep(0.3)
                EARN = got
                EARN_PATH.write_text(json.dumps(EARN))
                log(f"earnings calendar: {len(EARN)} companies ({filled} filled from company pages)")
                health("earnings calendar")
            else:
                health("earnings calendar", False, "empty")
        except Exception as e:
            log(f"earnings calendar failed: {e!r}")
            health("earnings calendar", False, e)
        time.sleep(4 * 3600)


def earnings_for(syms):
    return {t: jsonable(EARN[t]) for t in syms if t in EARN}


def earnings_history(sym):
    def run():
        df = yf.Ticker(sym).get_earnings_dates(limit=12)
        out = []
        for ts, row in zip(df.index, df.to_dict("records")):
            ts = pd.Timestamp(ts).tz_convert(NY)
            out.append({"date": ts.strftime("%Y-%m-%d"), "hour": ts.hour,
                        "epsEst": jsonable(row.get("EPS Estimate")), "eps": jsonable(row.get("Reported EPS")),
                        "surprise": jsonable(row.get("Surprise(%)"))})
        return out
    return cached(("earnhist", sym), 12 * 3600, run)


# ---------------------------------------------------------------- alerts
LINK_BASE = ""
HOST = "127.0.0.1"


def symbol_names():
    names = {}
    for f in FUNDS:
        for h in S.holdings.get(f, {}).get("holdings", []):
            names.setdefault(h["t"], h["n"])
    for (kind, *rest), (_, val) in list(_detail_cache.items()):
        if kind == "info" and isinstance(val, dict) and val.get("longName"):
            names[rest[0]] = val["longName"]
    return names


def alerts_loop():
    time.sleep(30)
    while True:
        try:
            with S.lock:
                px = {t: list(a[-260:]) for t, a in S.px.items()}
                dates = list(S.dates)
            names = symbol_names()
            for uid in personal.users():
                for t, title, _ in personal.evaluate(uid, px, dates, names, EARN, LINK_BASE, explain=explain_move):
                    log(f"alert for {uid}: {title}")
        except Exception as e:
            log(f"alerts failed: {e!r}")
        time.sleep(30)


# ---------------------------------------------------------------- why it moved: context for alerts and the close note
def day_change(a):
    last, prev, _ = personal._last2(a or [])
    return None if last is None or not prev else last / prev - 1


def typical_move(a, n=60):
    """The median size of a daily move over the last n sessions before today: what 'a normal day' means for this stock."""
    v = [x for x in (a or [])[:-1] if x is not None][-(n + 1):]
    r = sorted(abs(b / x - 1) for x, b in zip(v, v[1:]) if x)
    return r[len(r) // 2] if len(r) >= 20 else None


def _updown(c):
    return f"{'up' if c >= 0 else 'down'} {abs(c) * 100:.1f}%"


def move_reason(t, a, spy=None, peer=None):
    """Why a stock moved today, from numbers alone: how big the move is for this stock, and how much of it the
    market or its group explains. peer is (label, closes[, fund ticker]) or None. Returns {"size": x or None, "typ", "who", ...}."""
    c = day_change(a)
    if c is None:
        return None
    typ = typical_move(a)
    m = day_change(spy)
    p = day_change(peer[1]) if peer else None
    who = None
    if abs(c) >= 0.005:
        if m is not None and m * c > 0 and abs(m) >= 0.6 * abs(c):
            who = "market"
        elif p is not None and p * c > 0 and abs(p) >= 0.6 * abs(c):
            who = "group"
        else:
            base = p if p is not None else m
            who = "own" if base is None or base * c <= 0 or abs(base) < 0.3 * abs(c) else "mixed"
    return {"t": t, "c": c, "typ": typ, "size": abs(c) / typ if typ and typ > 0.001 else None,
            "m": m, "p": p, "peer": peer[0] if peer else None, "etf": peer[2] if peer and len(peer) > 2 else None, "who": who}


def reason_sentence(r, live=True):
    """The long form, appended to an alert: two plain sentences."""
    if not r:
        return ""
    out, t, c = [], r["t"], r["c"]
    if r["size"] and r["size"] >= 1.5:
        out.append(f"That's about {r['size']:.0f}× a normal day for {t}, which usually moves about {r['typ'] * 100:.1f}%.")
    elif r["size"] and r["size"] < 0.8 and abs(c) >= 0.01:
        out.append(f"That's an ordinary day for {t}, which usually moves about {r['typ'] * 100:.1f}%.")
    verb = "is" if live else "closed"
    parts = ([f"the S&P 500 {verb} {_updown(r['m'])}"] if r["m"] is not None and t != "SPY" else []) \
        + ([f"{r['peer']}{' (' + r['etf'] + ')' if r.get('etf') else ''} {'are' if live else 'closed'} {_updown(r['p'])}"]
           if r["p"] is not None else [])
    end = {"market": "so most of this is the whole market", "group": "so most of this is the group",
           "own": f"so this move is about {t} itself", "mixed": f"so it's partly the group and partly {t} itself"}.get(r["who"])
    if parts:
        s = " and ".join(parts)
        out.append(s[0].upper() + s[1:] + (f", {end}." if end else "."))
    return " ".join(out)


def reason_phrase(r):
    """The short form, for one line of the close note."""
    if not r:
        return ""
    bits = []
    if r["size"] and r["size"] >= 1.5:
        bits.append(f"{r['size']:.0f}× a normal day")
    bits.append({"market": "mostly the market", "group": f"mostly {r['peer'] or 'its group'}",
                 "own": "its own news", "mixed": f"partly {r['peer'] or 'its group'}"}.get(r["who"], ""))
    return ", ".join(b for b in bits if b)


def peer_for(t):
    """The group a stock moves with: chip stocks for anything in SMH, otherwise its sector fund.
    Returns (label, closes) or None."""
    if t in FUNDS or any(t == e for e, _, _ in X.SECTOR_ETFS):
        return None
    with S.lock:
        if any(h["t"] == t for f in ("SMH",) for h in S.holdings.get(f, {}).get("holdings", [])):
            a = S.px.get("SMH")
            return ("chip stocks", list(a[-3:]), "SMH") if a else None
        sector = str(S.sectors.get(t) or "").lower().replace(" ", "-")
        day = S.dates[-1] if S.dates else None
    etf = next(((e, n) for e, n, k in X.SECTOR_ETFS if k == sector), None)
    pair = _macro_pair(etf[0], day) if etf and day else None
    return (f"{etf[1].lower()} stocks", pair, etf[0]) if pair else None


def _macro_pair(sym, day):
    """[previous close, today] for an index or sector fund from the Market page's data, or None."""
    try:
        m = extra("macro", {})
        d = m["daily"]
        a = d["px"].get(sym) or []
        prev = [v for x, v in zip(d["dates"], a) if x < day and v is not None]
        today = (m["intraday"].get("last") or {}).get(sym) or next((v for x, v in zip(d["dates"], a) if x == day), None)
        return [prev[-1], today] if prev and today else None
    except Exception:
        return None


def explain_move(t):
    with S.lock:
        a, spy = list(S.px.get(t) or [])[-80:], list(S.px.get("SPY") or [])[-3:]
    return reason_sentence(move_reason(t, a, spy, peer_for(t)), live=market_open())


def _signed(c, places=1):
    return f"{'+' if c >= 0 else '−'}{abs(c) * 100:.{places}f}%"


def _when(day, other):
    d0, d1 = dt.date.fromisoformat(day), dt.date.fromisoformat(other)
    return "tomorrow" if (d1 - d0).days == 1 else d1.strftime("%A")


def close_note(uid, fetch=True):
    """The note sent at the close: the market in one line, your portfolio, your biggest movers and why, who reports next."""
    snap = personal.snapshot(uid)
    with S.lock:
        dates = list(S.dates)
        px = {t: list(a[-80:]) for t, a in S.px.items()}
        spy_hold = [h["t"] for h in S.holdings.get("SPY", {}).get("holdings", [])]
    if not dates:
        return None
    day = dates[-1]
    # the same index numbers the Market page leads with; the funds stand in when Yahoo's index data isn't there
    idx = [("S&P 500", day_change(_macro_pair("^GSPC", day)) if fetch else None, "SPY"),
           ("Nasdaq", day_change(_macro_pair("^IXIC", day)) if fetch else None, "QQQ")]
    idx = [(n, c if c is not None else day_change(px.get(f)), f) for n, c, f in idx]
    title = "Market close: " + ", ".join(f"{n} {_signed(c, 2)}" for n, c, _ in idx if c is not None)
    lines = []
    pos = [p for p in snap["positions"] if px.get(p["t"])]
    if pos:
        now = prev = 0.0
        for p in pos:
            last, before, _ = personal._last2(px[p["t"]])
            if last is not None and before:
                now += p["shares"] * last
                prev += p["shares"] * before
        if prev:
            d = now - prev
            lines.append(f"Your portfolio {'rose' if d >= 0 else 'fell'} {abs(d / prev) * 100:.1f}% "
                         f"({'+' if d >= 0 else '−'}${abs(d):,.0f}).")
    mine = sorted(set(snap["watch"]) | {p["t"] for p in snap["positions"]})
    pool = mine or spy_hold
    moves = sorted(((t, day_change(px.get(t))) for t in pool), key=lambda x: -abs(x[1] or 0))
    moves = [(t, c) for t, c in moves if c is not None][:3]
    if moves:
        if mine and abs(moves[0][1]) < 0.01:
            lines.append("Your stocks had a quiet day: none moved more than 1%.")
        else:
            head = "Your biggest movers" if mine else "Biggest moves in the S&P 500"
            items = []
            for t, c in moves:
                why = reason_phrase(move_reason(t, px.get(t), px.get("SPY"), peer_for(t))) if abs(c) >= 0.01 else ""
                items.append(f"{t} {_signed(c)}" + (f" ({why})" if why else ""))
            lines.append(f"{head}: " + "; ".join(items) + ".")
    nxt = personal._next_day(day)
    rep = []
    for t in mine:
        e = earnings_info(t, fetch=False)
        if (e.get("date") or "")[:10] == nxt and e.get("reported") is None:
            rep.append(t + {"BMO": " before the open", "AMC": " after the close"}.get(e.get("timing"), ""))
    if rep:
        lines.append(f"Reporting {_when(day, nxt)}: " + ", ".join(rep) + ".")
    return {"day": day, "title": title, "body": "\n".join(lines) or "A quiet day.", "live": market_open()}


def close_note_loop():
    """Once per trading day, about 15 minutes after the close, while the server runs."""
    time.sleep(60)
    while True:
        try:
            now = dt.datetime.now(NY)
            day = now.strftime("%Y-%m-%d")
            if now.weekday() < 5 and now.time() >= dt.time(16, 15) and S.dates and S.dates[-1] == day:
                for uid in personal.users():
                    if personal.settings(uid).get("close_note", "on") == "off" or personal.has_event(uid, f"close|{day}"):
                        continue
                    n = close_note(uid)
                    if n and personal.add_event(uid, None, "close", n["title"], n["body"], f"close|{day}"):
                        personal.push(uid, n["title"], n["body"], tag="bell", click=f"{LINK_BASE}/#mine" if LINK_BASE else None)
                        log(f"close note for {uid}: {n['title']}")
        except Exception as e:
            log(f"close note failed: {e!r}")
        time.sleep(60)


def user_for(handler) -> str:
    """One local user for now. Sign-in would map a session cookie to a user id here."""
    return personal.DEFAULT_USER


def me_payload(uid):
    out = personal.snapshot(uid)
    syms = set(out["watch"]) | {p["t"] for p in out["positions"]}
    out["earnings"] = earnings_for(syms)
    return out


# ---------------------------------------------------------------- research endpoints (analysts, options, market, ...)
def _upcoming_earnings(sym):
    e = earnings_info(sym)
    d = e.get("date")
    return d if d and d >= dt.date.today().isoformat() and e.get("reported") is None else None


def _ago(sec):
    if sec is None:
        return "never"
    sec = max(0, sec)
    if sec < 90:
        return f"{sec:.0f} seconds ago"
    if sec < 5400:
        return f"{sec / 60:.0f} minutes ago"
    if sec < 2 * 86400:
        return f"{sec / 3600:.0f} hours ago"
    return f"{sec / 86400:.0f} days ago"


def _business_days_since(day):
    try:
        d = pd.Timestamp(day).date()
    except Exception:
        return None
    return max(0, len(pd.bdate_range(d, dt.date.today())) - 1)


def _nice_day(day):
    """Any date an issuer or Yahoo gives us ("02-Nov-2026", "11/02/2026", "2026-11-02") as "Nov 2, 2026"."""
    try:
        d = pd.Timestamp(day).date()
    except Exception:
        return str(day)
    return f"{d:%b} {d.day}, {d.year}"


def health_report():
    """Plain-English data health: what's fresh, what's old, and what failed. Shown in Settings and `openticker doctor`."""
    now = time.time()
    rows, problems = [], []
    with S.lock:
        last_px = max(S.last_tick, S.last_poll)
        hist_at, last_day = S.history_fetched, (S.dates[-1] if S.dates else None)
        stream = S.stream_status
    open_ = market_open()
    rows.append({"name": "Live prices", "detail": (f"updated {_ago(now - last_px)}" if last_px else "waiting for the first update" if open_ else "market closed"),
                 "ok": not open_ or (last_px and now - last_px < 300)})
    if open_ and (not last_px or now - last_px >= 300):
        problems.append(f"Live prices haven't updated since {_ago(now - last_px) if last_px else 'the app started'}. The feed status is “{stream}”.")
    ny = dt.datetime.now(NY)
    traded_today = bool(last_px) and dt.datetime.fromtimestamp(last_px, NY).date() == ny.date()   # false on holidays
    behind = traded_today and ny.time() >= dt.time(16, 30) and last_day and last_day < ny.strftime("%Y-%m-%d") and now - hist_at > 600
    if behind:
        problems.append(f"Today's closing prices haven't come in yet, so “today” numbers still show {last_day}.")
    hist_ok = bool(hist_at) and now - hist_at < 30 * 3600 and not behind
    rows.append({"name": "Daily price history", "detail": f"through {_nice_day(last_day) if last_day else '?'}, fetched {_ago(now - hist_at) if hist_at else 'never'}", "ok": hist_ok})
    if not hist_ok:
        problems.append("Daily price history hasn't refreshed in over a day, so returns and charts may be behind.")
    for f in FUNDS:
        h = S.holdings.get(f) or {}
        age = _business_days_since(h.get("asOf")) if h.get("asOf") else None
        ok = bool(h.get("holdings")) and (age is None or age <= 3)
        rows.append({"name": f"{f} holdings", "detail": (f"as of {_nice_day(h.get('asOf'))}" if age is not None else "the top 10 from Yahoo; the issuer doesn't publish a full list we can read"
                     if not h.get("complete", True) else _nice_day(h.get("asOf")) if h.get("asOf") else "no date from the issuer"), "ok": ok})
        if not h.get("holdings"):
            problems.append(f"{f} holdings didn't load, so the Funds page can't show it.")
        elif age is not None and age > 3:
            problems.append(f"{f} holdings are from {_nice_day(h.get('asOf'))}, {age} business days old.")
    e = HEALTH.get("earnings calendar") or {}
    ok = bool(e.get("ok")) and now - e["ok"] < 12 * 3600
    rows.append({"name": "Earnings calendar", "detail": f"{len(EARN)} companies, refreshed {_ago(now - e['ok'])}" if e.get("ok") else f"{len(EARN)} companies from the last run, refreshing shortly", "ok": ok or not e})
    if e.get("fail") and (not e.get("ok") or e["fail"] > e["ok"]):
        problems.append("The earnings calendar didn't refresh last time. Dates may be missing for the last few hours.")
    research = {k: v for k, v in HEALTH.items() if not k.startswith("holdings") and k != "earnings calendar"}
    plain = {"earnhist": "earnings history", "econ": "the economic calendar", "info": "company profiles", "chart": "charts",
             "ecal": "earnings dates", "ohlc": "daily price bars", "analysts": "analysts", "financials": "financials",
             "ownership": "ownership and insiders", "options": "options", "events": "dividends and filings", "etf": "fund details",
             "sector": "sectors", "industry": "industries", "screen": "screens", "screens": "screens", "custom": "screens",
             "ipo": "IPOs", "splits": "splits", "mstatus": "market hours", "macro-daily": "macro prices", "macro-intra": "macro prices"}
    bad = sorted({plain.get(k, k) for k, v in research.items() if v.get("fail") and v["fail"] > v.get("ok", 0) and now - v["fail"] < 3600})
    rows.append({"name": "Research from Yahoo", "detail": "working" if research and not bad else "no requests yet" if not research
                 else "failing just now: " + ", ".join(bad), "ok": not bad})
    if bad:
        problems.append("Yahoo didn't answer for " + ", ".join(bad) + " just now. OpenTicker shows the last good copy where it has one.")
    return {"ok": not problems, "rows": rows, "problems": problems, "checked": now}


def _live_ttl(open_ttl, closed_ttl):
    return open_ttl if market_open() else closed_ttl


EXTRA = {
    # name: (needs ticker, ttl seconds, function(sym, query))
    "analysts":   (True,  6 * 3600,  lambda s, q: X.analysts(s)),
    "financials": (True,  24 * 3600, lambda s, q: X.financials(s)),
    "ownership":  (True,  12 * 3600, lambda s, q: X.ownership(s)),
    "options":    (True,  None,      lambda s, q: X.options(s, _upcoming_earnings(s), (q.get("exp") or [None])[0])),
    "events":     (True,  24 * 3600, lambda s, q: X.events(s)),
    "ohlc":       (True,  None,      lambda s, q: X.ohlc(s)),
    "etf":        (True,  24 * 3600, lambda s, q: X.etf(s)),
    "macro":      (False, None,      lambda s, q: {"daily": cached(("macro-daily",), 1800, X.macro_daily),
                                                   "intraday": cached(("macro-intra",), _live_ttl(60, 1800), X.macro_intraday),
                                                   "status": cached(("mstatus",), 300, X.market_status),
                                                   "names": {m[0]: [m[1], m[2]] for m in X.MACRO},
                                                   "sectors": [list(x) for x in X.SECTOR_ETFS]}),
    "sector":     (False, 24 * 3600, lambda s, q: X.sector_detail(re.sub(r"[^a-z-]", "", (q.get("key") or [""])[0]))),
    "industry":   (False, 24 * 3600, lambda s, q: X.industry_detail(re.sub(r"[^a-z-]", "", (q.get("key") or [""])[0]))),
    "screens":    (False, 24 * 3600, lambda s, q: X.screen_list()),
    "screen":     (False, 300,       lambda s, q: X.screen_predefined((q.get("name") or [""])[0])),
    "custom":     (False, 300,       lambda s, q: X.screen_custom({k: v[0] for k, v in q.items()})),
    "econ":       (False, 3600,      lambda s, q: X.economic_calendar()),
    "ipo":        (False, 6 * 3600,  lambda s, q: X.ipo_calendar()),
    "splits":     (False, 6 * 3600,  lambda s, q: X.splits_calendar()),
}


def extra(name, q):
    needs, ttl, fn = EXTRA[name]
    sym = None
    if needs:
        sym = yahoo_symbol((q.get("t") or [""])[0])
        if not VALID.fullmatch(sym):
            raise ValueError("bad symbol")
    if name == "options":
        ttl = _live_ttl(600, 3 * 3600)
    if name == "ohlc":
        ttl = _live_ttl(300, 6 * 3600)
    if name == "macro":
        return jsonable(fn(sym, q))
    key = ("x", name, sym, tuple(sorted((k, tuple(v)) for k, v in q.items() if k != "t")))
    return jsonable(cached(key, ttl, lambda: fn(sym, q)))


# ---------------------------------------------------------------- brief: what changed across your stocks
BRIEF_SOURCES = ("analysts", "ownership", "options")
_brief_fail: dict = {}          # (name, sym) -> time of last failure, so a stock without coverage isn't retried every pass
_brief_busy = threading.Lock()


def _xkey(name, sym):
    return ("x", name, sym, ())


def _xpeek(name, sym):
    with _detail_lock:
        hit = _detail_cache.get(_xkey(name, sym))
    return hit[1] if hit else None


def _is_fund(sym):
    if sym in FUNDS:
        return True
    with _detail_lock:
        hit = _detail_cache.get(("info", sym))
    return bool(hit and isinstance(hit[1], dict) and hit[1].get("quoteType") == "ETF")


def _brief_wanted(sym):
    return ("options",) if _is_fund(sym) else BRIEF_SOURCES


def brief_warm(uid=None):
    """Fill the research cache for every stock a user follows. One pass at a time; slow but polite to Yahoo."""
    if not _brief_busy.acquire(blocking=False):
        return
    try:
        syms = sorted(personal.all_symbols()) if uid is None else sorted(_user_syms(uid))
        for sym in syms:
            for name in _brief_wanted(sym):
                if _xpeek(name, sym) is not None and name != "options":
                    continue
                if time.time() - _brief_fail.get((name, sym), 0) < 6 * 3600:
                    continue
                try:
                    extra(name, {"t": [sym]})
                except Exception:
                    _brief_fail[(name, sym)] = time.time()
                time.sleep(0.4)
    finally:
        _brief_busy.release()


def brief_loop():
    time.sleep(90)
    while True:
        try:
            brief_warm()
        except Exception as e:
            log(f"brief warm failed: {e!r}")
        time.sleep(2 * 3600)


def _user_syms(uid):
    snap = personal.snapshot(uid)
    return set(snap["watch"]) | {p["t"] for p in snap["positions"]}


def _days_ago(d, today):
    try:
        return (today - dt.date.fromisoformat(d[:10])).days
    except Exception:
        return 999


def brief(uid):
    """Research-based items for the user's stocks: rating changes, target moves, estimate revisions,
    insider buying, big insider sales, unusual options and the move options price for earnings."""
    today = dt.date.today()
    syms = sorted(_user_syms(uid))
    items, pending = [], 0
    for sym in syms:
        for name in _brief_wanted(sym):
            if _xpeek(name, sym) is None and time.time() - _brief_fail.get((name, sym), 0) > 6 * 3600:
                pending += 1
        a = _xpeek("analysts", sym) or {}
        recent = [c for c in a.get("changes") or [] if _days_ago(c.get("date") or "", today) <= 14]
        for c in recent:
            act = (c.get("action") or "").lower()
            if act in ("up", "down", "init"):
                items.append({"t": sym, "kind": "rating", "date": c["date"], "tone": {"up": "up", "down": "down"}.get(act, ""),
                              "head": {"up": "Upgraded", "down": "Downgraded", "init": "Coverage started"}[act] + f" by {c.get('firm')}",
                              "text": (f"{c.get('from')} → " if c.get("from") and c.get("from") != c.get("to") else "") + (c.get("to") or "")
                                      + (f", target ${c['pt']:,.0f}" if c.get("pt") else ""),
                              "tab": "analysts", "score": 80})
        pts = [c for c in recent if c.get("pt") and c.get("ptPrior") and c["pt"] != c["ptPrior"]]
        if pts:
            ups = [c for c in pts if c["pt"] > c["ptPrior"]]
            avg = sum(c["pt"] / c["ptPrior"] - 1 for c in pts) / len(pts)
            dn = len(pts) - len(ups)
            items.append({"t": sym, "kind": "targets", "date": max(c["date"] for c in pts),
                          "tone": "" if (ups and dn and abs(avg) < 0.05) else "up" if avg > 0 else "down",
                          "head": (f"{len(ups)} price-target raise{'s' if len(ups) != 1 else ''}" if ups else "")
                                  + (" and " if ups and dn else "") + (f"{dn} cut{'s' if dn != 1 else ''}" if dn else ""),
                          "text": f"in two weeks, {avg * 100:+.0f}% on average. Latest: {pts[0].get('firm')} to ${pts[0]['pt']:,.0f}",
                          "tab": "analysts", "score": min(74, 52 + 3 * len(pts) + 60 * abs(avg))})
        et = (a.get("eps_trend") or {}).get("0y") or {}
        if et.get("current") and et.get("30daysAgo"):
            chg = et["current"] / et["30daysAgo"] - 1
            if abs(chg) >= 0.03:
                rv = (a.get("eps_revisions") or {}).get("0y") or {}
                items.append({"t": sym, "kind": "estimates", "date": today.isoformat(), "tone": "up" if chg > 0 else "down",
                              "head": f"This year's EPS estimate {'raised' if chg > 0 else 'cut'} {abs(chg) * 100:.1f}%",
                              "text": f"over 30 days, to ${et['current']:.2f}"
                                      + (f" ({rv.get('upLast30days') or 0} up, {rv.get('downLast30days') or 0} down)" if rv else ""),
                              "tab": "analysts", "score": 60})
        o = _xpeek("ownership", sym) or {}
        tx = o.get("insiders") or []
        buys = [x for x in tx if x.get("kind") == "buy" and _days_ago(x.get("date") or "", today) <= 60]
        if buys:
            v = sum(x.get("value") or 0 for x in buys)
            items.append({"t": sym, "kind": "insider", "date": max(x["date"] for x in buys), "tone": "up",
                          "head": f"Insider buying: {len(buys)} purchase{'s' if len(buys) != 1 else ''}",
                          "text": (f"${v / 1e6:,.1f}M " if v >= 1e6 else (f"${v:,.0f} " if v else "")) + "in the open market, latest by "
                                  + str(buys[0].get("insider") or "an insider").title(),
                          "tab": "ownership", "score": 75})
        sells = [x for x in tx if x.get("kind") == "sell" and _days_ago(x.get("date") or "", today) <= 30]
        sv = sum(x.get("value") or 0 for x in sells)
        if sv >= 20e6:
            items.append({"t": sym, "kind": "insider", "date": max(x["date"] for x in sells), "tone": "",
                          "head": f"Insiders sold ${sv / 1e6:,.0f}M this month",
                          "text": f"{len(sells)} sale{'s' if len(sells) != 1 else ''}; often planned in advance, so read it as context rather than a signal",
                          "tab": "ownership", "score": 35})
        op = _xpeek("options", sym) or {}
        e = op.get("earnings") or {}
        if e.get("move") and e.get("earningsDate") and 0 <= -_days_ago(e["earningsDate"], today) <= 10:
            items.append({"t": sym, "kind": "earnings", "date": e["earningsDate"], "tone": "",
                          "head": "Earnings " + dt.date.fromisoformat(e["earningsDate"]).strftime("%a %b %-d"),
                          "text": f"options price a ±{e['move'] * 100:.1f}% move", "tab": "options", "score": 70, "future": True})
        unusual = [u for u in op.get("unusual") or [] if (u.get("volume") or 0) >= 2000]
        if unusual:
            u = unusual[0]
            calls = sum(1 for x in unusual if x.get("side") == "call")
            items.append({"t": sym, "kind": "options", "date": today.isoformat(), "tone": "up" if calls > len(unusual) / 2 else "down" if calls < len(unusual) / 2 else "",
                          "head": f"Unusual options: {len(unusual)} busy contract{'s' if len(unusual) != 1 else ''}",
                          "text": f"biggest is the ${u['strike']:g} {u['side']} for {dt.date.fromisoformat(u['expiry']).strftime('%b %-d')}, "
                                  f"{u['volume']:,} traded vs {u['oi']:,} open",
                          "tab": "options", "score": 45})
    if pending and not _brief_busy.locked():
        threading.Thread(target=brief_warm, args=(uid,), daemon=True).start()
    return {"items": jsonable(items), "pending": pending, "count": len(syms)}


# ---------------------------------------------------------------- static files
STATIC = HERE / "static"
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                ".png": "image/png", ".webmanifest": "application/manifest+json", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body: bytes, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # JSON only: a cross-site form can't send application/json without a CORS preflight we never allow
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, b"json only", "text/plain")
        if self.path.split("?")[0] == "/api/ask":
            return self.ask()
        if self.path.split("?")[0] == "/api/ask/chat/delete":
            if not agent.may_ask(self):
                return self.send(403, b'{"error":"not allowed"}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
            except Exception:
                return self.send(400, b"bad json", "text/plain")
            personal.chat_delete(user_for(self), str(body.get("id") or ""))
            return self.send(200, b'{"ok":true}', "application/json")
        if self.path.split("?")[0] == "/api/app/terminal":
            if not (agent.is_local(self) and agent.host_ok(self)):
                return self.send(403, b'{"error":"Only on the Mac itself."}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
                ok = agent.open_app_terminal(str(body.get("step")))
                return self.send(200, json.dumps({"ok": ok}).encode(), "application/json")
            except ValueError as e:
                return self.send(400, json.dumps({"error": str(e)}).encode(), "application/json")
        if self.path.split("?")[0] == "/api/ask/terminal":
            if not (agent.is_local(self) and agent.host_ok(self)):
                return self.send(403, b'{"error":"Only on the Mac itself."}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
                ok = agent.open_terminal(str(body.get("provider")), str(body.get("action")))
                return self.send(200, json.dumps({"ok": ok}).encode(), "application/json")
            except ValueError as e:
                return self.send(400, json.dumps({"error": str(e)}).encode(), "application/json")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 262144)) or b"{}")
        except Exception:
            return self.send(400, b"bad json", "text/plain")
        uid, path = user_for(self), self.path.split("?")[0]

        def sym():
            t = yahoo_symbol(str(body.get("t") or ""))
            if not VALID.fullmatch(t):
                raise ValueError("That isn't a ticker symbol.")
            if t not in S.px and not S.track(t):
                raise ValueError(f"Couldn't find prices for {t}.")
            return t

        def num(k, required=True):
            v = body.get(k)
            if v in (None, ""):
                if required:
                    raise ValueError(f"{k} is required.")
                return None
            v = float(v)
            if not math.isfinite(v):
                raise ValueError(f"{k} must be a number.")
            return v

        try:
            if path == "/api/me/watch":
                personal.set_watch(uid, sym(), bool(body.get("on", True)))
            elif path == "/api/me/position":
                shares, cost = num("shares"), num("cost")
                if shares <= 0 or cost < 0:
                    raise ValueError("Shares must be above zero and cost can't be negative.")
                opened = str(body.get("opened") or "")[:10]
                if body.get("id"):
                    personal.update_position(uid, body["id"], shares, cost, opened)
                else:
                    personal.clear_sample(uid)   # a real position replaces the sample portfolio
                    personal.add_position(uid, sym(), shares, cost, opened)
            elif path == "/api/me/positions/import":
                rows = body.get("rows") or []
                if not isinstance(rows, list) or not rows or len(rows) > 500:
                    raise ValueError("Nothing to import.")
                clean_rows, bad = [], []
                for r in rows:
                    t = yahoo_symbol(str((r or {}).get("t") or ""))
                    try:   # no cost in the file: count gains from today's price
                        shares, cost = float(r.get("shares")), (-1.0 if r.get("cost") in (None, "") else float(r.get("cost")))
                    except (TypeError, ValueError):
                        bad.append(t or "?")
                        continue
                    if not VALID.fullmatch(t) or not (0 < shares < 1e12) or not (cost == -1 or 0 <= cost < 1e9):
                        bad.append(t or "?")
                        continue
                    clean_rows.append((t, shares, cost))
                priced = S.track_many([t for t, _, _ in clean_rows])
                bad += sorted({t for t, _, _ in clean_rows if t not in priced})
                with S.lock:
                    last = {t: next((v for v in reversed(S.px.get(t) or []) if v is not None), None) for t in priced}
                keep = [(t, sh, c if c >= 0 else last[t]) for t, sh, c in clean_rows if t in priced and (c >= 0 or last[t])]
                if not keep:
                    raise ValueError("None of those rows had a ticker with prices on Yahoo.")
                personal.import_positions(uid, keep, replace=bool(body.get("replace")), note="sample" if body.get("sample") else "imported")
                out = me_payload(uid)
                out["imported"], out["skipped"] = len(keep), bad
                with S.lock:
                    S.version += 1
                return self.send(200, json.dumps(out).encode(), "application/json")
            elif path == "/api/me/positions/clear-sample":
                personal.clear_sample(uid)
            elif path == "/api/me/position/delete":
                personal.delete_position(uid, body.get("id"))
            elif path == "/api/me/alert":
                t = sym() if body.get("t") else None
                personal.add_alert(uid, str(body.get("kind")), t, body.get("scope"), num("value", required=False))
            elif path == "/api/me/alert/toggle":
                personal.set_alert_active(uid, body.get("id"), bool(body.get("on")))
            elif path == "/api/me/alert/delete":
                personal.delete_alert(uid, body.get("id"))
            elif path == "/api/me/settings":
                if "closeNote" in body:
                    personal.set_setting(uid, "close_note", "on" if body.get("closeNote") else "off")
                if "ntfyTopic" in body:
                    topic = re.sub(r"[^A-Za-z0-9_-]", "", str(body.get("ntfyTopic") or ""))[:64]
                    srv = str(body.get("ntfyServer") or "https://ntfy.sh").strip()
                    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", srv.rstrip("/")):
                        raise ValueError("The ntfy server must be an https:// address.")
                    personal.set_setting(uid, "ntfy_topic", topic)
                    personal.set_setting(uid, "ntfy_server", srv.rstrip("/"))
            elif path == "/api/me/read":
                personal.mark_read(uid)
            elif path == "/api/me/test-push":
                if not personal.push(uid, "OpenTicker test", "Alerts from your dashboard will arrive here.", "bell"):
                    raise ValueError("Couldn't send. Check the topic name and that this Mac is online.")
            else:
                return self.send(404, b"not found", "text/plain")
        except (ValueError, TypeError) as e:
            return self.send(400, json.dumps({"error": str(e)}).encode(), "application/json")
        with S.lock:
            S.version += 1   # pages refetch base, so new tickers show up with prices
        self.send(200, json.dumps(me_payload(uid)).encode(), "application/json")

    # ------------------------------------------------------------ ask an agent (streams Server-Sent Events)
    def ask(self):
        if not agent.may_ask(self):
            return self.send(403, json.dumps({"error": "Ask runs agents signed in on your Mac, so it only works there or on a paired phone."}).encode(), "application/json")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 200_000)) or b"{}")
        except Exception:
            return self.send(400, b"bad json", "text/plain")
        prov = str(body.get("provider") or "claude")
        if prov not in {p["id"] for p in agent.PROVIDERS}:
            return self.send(400, json.dumps({"error": "Unknown agent."}).encode(), "application/json")
        uid = user_for(self)
        scope = body.get("scope") if body.get("scope") in ("stock", "portfolio", "market", "fund") else "market"
        t = yahoo_symbol(str(body.get("t") or "")) if body.get("t") else ""
        if t and not VALID.fullmatch(t):
            t = ""
        sk = agent.skill(str(body.get("skill") or "")) if body.get("skill") else None
        q = str(body.get("q") or "").strip()[:4000] or (sk["prompt"].replace("{t}", t or "this stock") if sk else "")
        if not q:
            return self.send(400, json.dumps({"error": "Ask a question."}).encode(), "application/json")
        hist = [h for h in body.get("history") or [] if isinstance(h, dict)][-6:]
        cid = str(body.get("chat") or "")
        cid = cid if re.fullmatch(r"[\w-]{8,40}", cid) else ""
        if cid:
            try:
                personal.chat_add(uid, cid, {"role": "user", "text": str(body.get("show") or q)[:4000], "ctx": {"scope": scope, "t": t or None},
                                             "skill": sk["name"] if sk else None, "ts": time.time()})
            except PermissionError:
                cid = ""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        wlock, state = threading.Lock(), {"alive": True, "run": None}

        acc = {"text": "", "steps": [], "tool": False, "by": None, "error": None, "on": False}

        def remember(kind, payload):
            """Keep what the user saw, so the conversation is still there after a reload or on the phone."""
            if not acc["on"]:
                return
            if kind == "text":
                acc["text"] += payload.get("text", "")
                acc["tool"] = False
            elif kind == "status":
                acc["steps"].append(payload.get("text", ""))
                acc["tool"] = bool(acc["text"])
            elif kind == "turn" and acc["tool"]:
                acc["text"], acc["tool"] = "", False
            elif kind == "meta" and payload.get("model"):
                acc["by"] = payload["model"]
                agent.remember_model(prov, body.get("model"), payload["model"])
            elif kind == "error":
                acc["error"] = payload.get("message")

        def emit(kind, payload):
            remember(kind, payload)
            if not state["alive"]:
                return
            try:
                with wlock:
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps(payload)}\n\n".encode())
                    self.wfile.flush()
            except Exception:
                state["alive"] = False
                if state["run"]:
                    state["run"].cancel()

        label = next(p["label"] for p in agent.PROVIDERS if p["id"] == prov)
        emit("status", {"text": "Gathering the data"})
        try:
            ctx = agent.context_for(scope, t, uid)
        except Exception as e:
            log(f"ask context failed: {e!r}")
            ctx = "(Live data wasn't available just now.)"
        emit("status", {"text": f"Asking {label}"})
        run = agent.Run(prov, agent.build_prompt(q, ctx, sk, hist, tools=prov != "ollama"), emit, body.get("model"), body.get("effort"))
        state["run"] = run
        t0 = time.time()
        acc["on"] = True
        run.run()
        if cid:
            stopped = not state["alive"] or run.cancelled
            personal.chat_add(uid, cid, {"role": "assistant", "text": acc["text"], "steps": acc["steps"][:24],
                                         "by": label + (f" · {acc['by']}" if acc["by"] else ""), "secs": round(time.time() - t0),
                                         "error": acc["error"] or ("Stopped." if stopped and not acc["text"] else None), "ts": time.time()})
        log(f"ask via {prov} ({sk['name'] if sk else 'question'}, {scope} {t}) took {time.time() - t0:.0f}s")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/base":
            if not S.dates:   # first launch, still downloading
                return self.send(503, json.dumps({"loading": True, "step": S.boot}).encode(), "application/json")
            self.send(200, json.dumps(S.snapshot_base(), separators=(",", ":")).encode(), "application/json")
        elif path == "/api/live":
            self.send(200, json.dumps(S.snapshot_live(), separators=(",", ":")).encode(), "application/json")
        elif path.startswith("/api/x/") and path[7:] in EXTRA:
            try:
                body = extra(path[7:], parse_qs(urlsplit(self.path).query))
                self.send(200, json.dumps(body, separators=(",", ":")).encode(), "application/json")
            except ValueError as e:
                self.send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            except Exception as e:
                log(f"{path} failed: {e!r}")
                self.send(502, json.dumps({"error": "Yahoo Finance isn't answering right now."}).encode(), "application/json")
        elif path.startswith("/static/"):
            name = path[8:]
            f = STATIC / name
            if not re.fullmatch(r"(fonts/)?[a-z0-9-]+\.(js|css|svg|png|webmanifest|woff2|txt)", name) or not f.is_file():
                return self.send(404, b"not found", "text/plain")
            self.send(200, f.read_bytes(), STATIC_TYPES[f.suffix])
        elif path.startswith("/api/agent/"):
            try:
                text = agent.text_for(path[11:], parse_qs(urlsplit(self.path).query), user_for(self))
                self.send(200, text.encode(), "text/markdown; charset=utf-8")
            except ValueError as e:
                self.send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            except Exception as e:
                log(f"{path} failed: {e!r}")
                self.send(502, json.dumps({"error": "Yahoo Finance isn't answering right now."}).encode(), "application/json")
        elif path == "/api/app":
            local = agent.is_local(self)
            ver = paths.ROOT / "VERSION"
            self.send(200, json.dumps({
                "version": ver.read_text().strip() if ver.exists() else "0.1.0",
                "local": local, "phone": HOST == "0.0.0.0", "port": PORT,
                "data": str(paths.HOME) if local else None, "mac": sys.platform == "darwin",
            }).encode(), "application/json")
        elif path == "/api/health":
            self.send(200, json.dumps(jsonable(health_report())).encode(), "application/json")
        elif path == "/api/ask/info":
            ok = agent.may_ask(self)
            self.send(200, json.dumps({
                "allowed": ok, "local": agent.is_local(self),
                "providers": agent.providers(force="refresh" in (self.path.split("?") + [""])[1]) if ok else [],
                "skills": [{k: s[k] for k in ("name", "label", "scope", "prompt", "description", "blurb")} for s in agent.skills()],
                "pair": (f"{LINK_BASE or 'http://' + (self.headers.get('Host') or '')}/#pair={agent.pair_token()}" if agent.is_local(self) and agent.host_ok(self) else None),
            }).encode(), "application/json")
        elif path in ("/api/ask/chats", "/api/ask/chat"):
            if not agent.may_ask(self):
                return self.send(403, b'{"error":"not allowed"}', "application/json")
            uid = user_for(self)
            if path.endswith("chats"):
                body = personal.chats(uid)
            else:
                body = personal.chat(uid, (parse_qs(urlsplit(self.path).query).get("id") or [""])[0]) or {"error": "not found"}
            self.send(200, json.dumps(body).encode(), "application/json")
        elif path == "/api/brief":
            self.send(200, json.dumps(brief(user_for(self))).encode(), "application/json")
        elif path == "/api/me":
            self.send(200, json.dumps(me_payload(user_for(self))).encode(), "application/json")
        elif path == "/api/me/close-note":
            self.send(200, json.dumps(jsonable(close_note(user_for(self)) or {})).encode(), "application/json")
        elif path == "/api/earnings":
            with S.lock:
                syms = set(S.px)
            self.send(200, json.dumps(earnings_for(syms)).encode(), "application/json")
        elif path == "/api/earnhist":
            sym = yahoo_symbol((parse_qs(urlsplit(self.path).query).get("t") or [""])[0])
            try:
                body = earnings_history(sym) if VALID.fullmatch(sym) else []
                self.send(200, json.dumps(body).encode(), "application/json")
            except Exception:
                self.send(502, json.dumps({"error": "Yahoo didn't return earnings history."}).encode(), "application/json")
        elif path == "/api/search":
            q = (parse_qs(urlsplit(self.path).query).get("q") or [""])[0].strip()[:40]
            try:
                body = search_tickers(q) if q else []
            except Exception:
                body = []
            self.send(200, json.dumps(body).encode(), "application/json")
        elif path == "/api/track":
            sym = yahoo_symbol((parse_qs(urlsplit(self.path).query).get("t") or [""])[0])
            ok = bool(VALID.fullmatch(sym)) and S.track(sym)
            self.send(200 if ok else 404, json.dumps({"ok": ok, "t": sym}).encode(), "application/json")
        elif path in ("/api/stock", "/api/chart"):
            q = parse_qs(urlsplit(self.path).query)
            sym = (q.get("t") or [""])[0]
            if not VALID.fullmatch(yahoo_symbol(sym)):
                return self.send(400, b"bad symbol", "text/plain")
            try:
                if path == "/api/stock":
                    body = stock_detail(sym)
                else:
                    body = stock_chart(sym, (q.get("r") or ["1M"])[0], (q.get("vs") or [None])[0])
                self.send(200, json.dumps(body, separators=(",", ":")).encode(), "application/json")
            except Exception as e:
                self.send(502, json.dumps({"error": f"Yahoo didn't answer ({type(e).__name__})."}).encode(),
                          "application/json")
        else:
            self.send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 makes it reachable from other devices on your Wi-Fi (e.g. your phone)")
    ap.add_argument("--no-stream", action="store_true")
    args = ap.parse_args()

    global LINK_BASE, PORT, HOST
    PORT, HOST = args.port, args.host
    personal.init()
    agent.bind(sys.modules[__name__])
    # Serve right away: from the last run's prices if there are any, otherwise a loading screen that says what's
    # happening. Fresh holdings and history download behind it, then the background loops start.
    S.load_cache()
    load_disk_cache()
    threading.Thread(target=disk_cache_loop, daemon=True).start()

    def warm():
        while True:
            try:
                S.boot = "Getting what SPY, QQQ, SMH and SPSM hold"
                S.holdings = {k: v for k, v in load_holdings().items() if k in FUNDS}
                S.boot = f"Getting a year of daily prices for {len(S.tickers())} stocks and funds"
                S.load_history()
                break
            except Exception as e:
                log(f"startup download failed, trying again in 30 seconds: {e!r}")
                S.boot = "Yahoo Finance didn't answer. Trying again in a moment"
                time.sleep(30)
        S.boot = ""
        threading.Thread(target=earnings_loop, daemon=True).start()
        threading.Thread(target=alerts_loop, daemon=True).start()
        threading.Thread(target=close_note_loop, daemon=True).start()
        threading.Thread(target=brief_loop, daemon=True).start()
        if not args.no_stream:
            threading.Thread(target=stream_loop, daemon=True).start()
        threading.Thread(target=poll_loop, daemon=True).start()
        threading.Thread(target=sector_loop, daemon=True).start()

    threading.Thread(target=warm, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"OpenTicker running at http://127.0.0.1:{args.port}")
    if args.host == "0.0.0.0":
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
            host = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
            log(f"On your phone (same Wi-Fi): http://{ip}:{args.port}  or  http://{host}.local:{args.port}")
            if host:
                LINK_BASE = f"http://{host}.local:{args.port}"
        except Exception:
            pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
