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
import html
import json
import math
import mimetypes
import re
import secrets
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
import links  # noqa: E402
import paths  # noqa: E402
import personal  # noqa: E402
import runs  # noqa: E402
import signals  # noqa: E402
import workbench  # noqa: E402
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


def session_closes(syms, day):
    """Each symbol's last regular-session price on `day` from minute bars. Yahoo's daily download leaves the
    current session's close empty until well after the close (DUOL on 2026-11-04 had a row with no price), so a
    symbol fetched from it would otherwise sit at the previous close all evening."""
    if not syms or not day:
        return {}
    try:
        m = download_closes(syms, period="1d", interval="1m")
    except Exception as e:
        log(f"couldn't get {day} from minute bars: {e!r}")
        return {}
    if m.empty:
        return {}
    days = [pd.Timestamp(i).tz_convert(NY).strftime("%Y-%m-%d") for i in m.index]
    m = m[[d == day for d in days]]
    if m.empty:
        return {}
    last = m.ffill().iloc[-1]
    return {t: round(float(v), 4) for t, v in last.items() if v is not None and v == v}


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


NAMES_PATH = CACHE / "names.json"   # company names for symbols outside the funds (positions, watchlist, search)


def load_sectors():
    return json.loads(SECTORS_PATH.read_text()) if SECTORS_PATH.exists() else {}


def load_names():
    try:
        return json.loads(NAMES_PATH.read_text()) if NAMES_PATH.exists() else {}
    except Exception:
        return {}


def sector_loop():
    """Fill in GICS-style sectors from Yahoo once per symbol, slowly, and cache them."""
    time.sleep(5)
    while True:
        known, names = load_sectors(), load_names()
        with S.lock:
            held = {h["t"] for f in S.holdings.values() for h in f.get("holdings", [])}
        todo = [t for t in S.tickers() if t not in FUNDS and (t not in known or (t not in held and t not in names))]
        if todo:
            log(f"looking up sectors for {len(todo)} symbols")
        added = 0
        for t in todo:
            try:
                info = yf.Ticker(t).get_info()
                known[t] = info.get("sector") or info.get("quoteType", "Other").title()
                if t not in held and (info.get("longName") or info.get("shortName")):
                    names[t] = info.get("longName") or info.get("shortName")
                added += 1
            except Exception as e:
                log(f"sector {t} failed: {e!r}")
                time.sleep(5)
            time.sleep(0.25)
            if added and added % 50 == 0:
                SECTORS_PATH.write_text(json.dumps(known))
                NAMES_PATH.write_text(json.dumps(names))
                with S.lock:
                    S.sectors, S.names = dict(known), dict(names)
                    S.version += 1
        if added:
            SECTORS_PATH.write_text(json.dumps(known))
            NAMES_PATH.write_text(json.dumps(names))
            with S.lock:
                S.sectors, S.names = dict(known), dict(names)
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
        self.tick_at: dict = {}       # sym -> wall time of its last streamed regular-hours tick
        self.stream_since = 0.0
        self.ticks = 0
        self.last_poll = 0.0
        self.poll_after = 0.0         # no polling before this (the minute bars weren't today's)
        self.history_fetched = 0.0
        self.boot = "Starting up"   # what the first launch is doing, shown on the loading screen
        self.stream_status = "starting"
        self.sectors = load_sectors()
        self.names = load_names()
        self.extras: list[str] = []   # tickers opened from search that aren't in any fund
        self.ext: dict = {}           # pre-market and after-hours trades: sym -> (price, unix time, "pre"|"post", NY date)
        self.last_ext_tick = 0.0

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
            empty = [s for s in have if self.px[s] and self.px[s][-1] is None and any(v is not None for v in self.px[s][-6:-1])]   # tracked before the session's close was out
        if empty and dates:
            got = session_closes(empty, dates[-1])
            with self.lock:
                if self.dates == dates:
                    for t, v in got.items():
                        self.px[t][-1] = v
                    self.version += bool(got)
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
        holes = [t for t, a in got.items() if a[-1] is None]
        for t, v in session_closes(holes, dates[-1]).items():
            got[t][-1] = v
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
        return have | set(got)   # stream_loop subscribes them within half a minute

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
        # the same gap for single symbols: the session's row is there but some closes in it are still empty
        if session and dates and dates[-1] == session:
            holes = [t for t, a in px.items() if a and a[-1] is None and any(v is not None for v in a[-6:-1])]
            got = session_closes(holes, session)
            for t, v in got.items():
                px[t][-1] = v
            if holes:
                log(f"filled {len(got)}/{len(holes)} empty {session} closes from minute bars")
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

    def apply_ext(self, sym, price, ts):
        """A trade outside the regular session. Only pre-market (4 to 9:30) and after hours (4 to 8 pm) count."""
        if price is None or sym not in self.px:
            return
        when = dt.datetime.fromtimestamp(ts, NY)
        sess = ext_session(when)
        if not sess:
            return
        old = self.ext.get(sym)
        if old and old[1] > ts:
            return
        self.ext[sym] = (round(float(price), 4), int(ts), sess, when.strftime("%Y-%m-%d"))

    def ext_view(self):
        """The extended-hours prices that matter right now, Yahoo style: pre-market before the open, after hours
        from the close until the next pre-market, nothing during the regular session. Change is from the last close."""
        now = dt.datetime.now(NY)
        weekday = X.session_hours(now.date()) is not None    # a trading day
        if weekday and dt.time(9, 30) <= now.time() < dt.time(16, 0) or not self.dates:
            return {}
        pre_now = weekday and dt.time(4, 0) <= now.time() < dt.time(9, 30)
        today, last_day = now.strftime("%Y-%m-%d"), self.dates[-1]
        out = {}
        for sym, (p, ts, sess, day) in self.ext.items():
            if (sess, day) != (("pre", today) if pre_now else ("post", last_day)):
                continue
            a = self.px.get(sym) or []
            close = a[-1] if a else None
            if close:
                out[sym] = [p, ts, sess, round(p / close - 1, 6)]
        return out

    def snapshot_live(self):
        with self.lock:
            return {
                "v": self.version,
                "date": self.dates[-1] if self.dates else None,
                "last": {t: a[-1] for t, a in self.px.items() if a},
                "ext": self.ext_view(),
                "lastTick": self.last_tick,
                "ticks": self.ticks,
                "stream": self.stream_status,
                "lastPoll": self.last_poll,
                "open": market_open(),      # the exchange's hours, so a dead feed isn't mistaken for a closed market
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
                "names": self.names,
                "extras": self.extras,
                "historyFetched": self.history_fetched,
            }


def ext_session(when):
    """'pre' or 'post' for a New York time inside those sessions on a weekday, else None."""
    if not X.session_hours(when.date()):     # weekends and market holidays
        return None
    t = when.time()
    return "pre" if dt.time(4, 0) <= t < dt.time(9, 30) else "post" if dt.time(16, 0) <= t < dt.time(20, 0) else None


S = State()


STREAM_CHUNK = 90   # Yahoo's stream only sends about 100 symbols per connection and drops the rest without a word


def on_stream_msg(m):
        try:
            ts = int(m.get("time", 0)) / 1000
            if m.get("market_hours") != 1:      # pre-market or after hours: kept apart from the daily close
                with S.lock:
                    S.apply_ext(m["id"], m.get("price"), ts)
                S.last_ext_tick = time.time()
                return
            day = dt.datetime.fromtimestamp(ts, NY).strftime("%Y-%m-%d")
            S.apply_price(m["id"], m.get("price"), day)
            S.last_tick = S.tick_at[m["id"]] = time.time()
            S.ticks += 1
            S.stream_status = "live"
        except Exception:
            pass


def stream_shard(syms):
    """One stream connection for up to STREAM_CHUNK symbols. Reconnects forever."""
    while True:
        try:
            ws = yf.WebSocket(verbose=False)
            ws.subscribe(syms)
            if S.stream_status != "live":
                S.stream_status = "connected"
            ws.listen(on_stream_msg)
        except Exception as e:
            if time.time() - S.last_tick > 60:
                S.stream_status = "reconnecting"
            log(f"stream dropped ({len(syms)} symbols from {syms[0]}): {e!r}")
        time.sleep(5)


def stream_loop():
    """Yahoo streaming quotes, split across connections. Symbols added later (a searched ticker, a new position)
    get their own connection within half a minute."""
    covered = set()
    S.stream_since = time.time()
    while True:
        try:
            new = [t for t in S.tickers() if t not in covered]
            for i in range(0, len(new), STREAM_CHUNK):
                part = new[i:i + STREAM_CHUNK]
                covered.update(part)
                threading.Thread(target=stream_shard, args=(part,), daemon=True).start()
            if new:
                log(f"stream subscribed to {len(covered)} symbols over {math.ceil(len(covered) / STREAM_CHUNK)}+ connections")
        except Exception as e:
            log(f"stream setup failed: {e!r}")
        time.sleep(30)


def poll_loop():
    """Fallback when the stream is quiet during market hours, plus periodic refreshes."""
    while True:
        time.sleep(15)
        try:
            now_ny = dt.datetime.now(NY)
            open_ = market_open(now_ny)
            if time.time() - S.history_fetched > HISTORY_TTL:
                old = S.holdings
                S.holdings = {k: v for k, v in load_holdings().items() if k in FUNDS} or old
                S.load_history()
                continue
            quiet = time.time() - S.last_tick > POLL_FALLBACK
            # symbols the stream hasn't priced in five minutes (it can go silent on some while others keep ticking)
            stale = [t for t in S.tickers() if time.time() - S.tick_at.get(t, 0) > 300] \
                if open_ and not quiet and S.stream_since and time.time() - S.stream_since > 300 else []
            if open_ and (quiet or len(stale) > 20) and time.time() - S.last_poll > (POLL_FALLBACK if quiet else 180) \
                    and time.time() > S.poll_after:
                syms = S.tickers() if quiet else stale
                df = download_closes(syms, period="1d", interval="1m")
                day = now_ny.strftime("%Y-%m-%d")
                # only today's bars count: a day the exchange closed unexpectedly returns the last session's, and
                # filing those under today would invent a trading day (every change 0.0%, and a close note for it)
                bar_day = pd.Timestamp(df.index[-1]).tz_convert(NY).strftime("%Y-%m-%d") if len(df.index) else None
                if bar_day != day:
                    S.poll_after = time.time() + 600       # look again in ten minutes
                    log(f"polled, but the latest minute bars are from {bar_day}, not today; not using them")
                    continue
                last = df.ffill().iloc[-1]
                for sym, v in last.items():
                    if v == v:
                        S.apply_price(sym, float(v), day)
                S.last_poll = time.time()
                if S.stream_status != "live":
                    S.stream_status = "polling"
                log("polled prices (stream quiet)" if quiet else f"polled {len(syms)} prices the stream hasn't sent")
        except Exception as e:
            log(f"poll failed: {e!r}")


def ext_poll():
    """Pre-market and after-hours prices for everything, from one-minute bars that include extended hours."""
    df = download_closes(S.tickers(), period="1d", interval="1m", prepost=True)
    n = 0
    with S.lock:
        for sym in df.columns:
            col = df[sym].dropna()
            if len(col):
                S.apply_ext(sym, float(col.iloc[-1]), col.index[-1].timestamp())
                n += 1
    log(f"extended-hours prices for {n} symbols")


def ext_loop():
    """Fill in pre-market and after-hours prices once at start, then every ten minutes in those sessions
    when the stream is quiet, and once more just after 8 pm so the final after-hours price is right."""
    last, closing_done = 0.0, None
    while True:
        try:
            now = dt.datetime.now(NY)
            sess = ext_session(now)
            day = now.strftime("%Y-%m-%d")
            late = now.weekday() < 5 and dt.time(20, 2) <= now.time() < dt.time(21, 0) and closing_done != day
            due = (not last and not market_open()) or late or \
                (sess and time.time() - last > 600 and time.time() - S.last_ext_tick > 180)
            if due:
                last = time.time()
                ext_poll()
                if late:
                    closing_done = day
        except Exception as e:
            log(f"extended-hours poll failed: {e!r}")
        time.sleep(60)


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
    # key stats and the balance sheet
    "sharesOutstanding", "floatShares", "totalCash", "totalDebt", "ebitda", "netIncomeToCommon", "payoutRatio",
    "exDividendDate", "bookValue", "heldPercentInsiders", "returnOnAssets", "currentRatio",
    # funds
    "totalAssets", "netAssets", "netExpenseRatio", "yield", "ytdReturn", "beta3Year", "fundFamily", "category",
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


def _yf_fresh():
    """yfinance keeps its own copy of every Yahoo answer with no expiry (an LRU on YfData.cache_get), so after our TTL ran
    out we'd get the same old answer back: the market stayed "closed" all morning. Drop it before each real fetch."""
    try:
        from yfinance.data import YfData
        YfData.cache_get.cache_clear()
    except Exception:
        pass


def _absent(e):
    """Whether Yahoo answered that it has nothing for this symbol, as opposed to failing."""
    return bool(re.search(r"\b404\b|Not Found|No fundamentals data", str(e)))


def cached(key, ttl, fn):
    """Small TTL cache. Yahoo fails now and then for a moment, so a failed fetch is tried once more; if it still
    fails we serve the last good copy, from memory or from the last run (cache/detail.json), when there is one."""
    now = time.time()
    with _detail_lock:
        hit = _detail_cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    _yf_fresh()
    try:
        try:
            val = fn()
        except Exception as e:
            if _absent(e):
                raise
            log(f"{key} failed, trying once more: {e!r}")
            time.sleep(1.2)
            val = fn()
    except Exception as e:
        log(f"{key} failed: {e!r}")
        if not _absent(e):          # Yahoo has no such data for this symbol (a fund's analysts, say): not an outage
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
        h = tk.history(period="2y", interval="1d", auto_adjust=True, prepost=False)
        # Yahoo leaves the current session's close empty until well after the close; use the quote's price for it
        # rather than dropping the day, or every range would end at yesterday (DUOL's +26% on 2026-11-04)
        px = (tk.history_metadata or {}).get("regularMarketPrice")
        if len(h.index) and h["Close"].iloc[-1] != h["Close"].iloc[-1] and px:
            h.loc[h.index[-1], "Close"] = float(px)
        h = h.dropna(subset=["Close"])
        avgs = {n: h["Close"].rolling(n).mean() for n in MA_DAYS}
        last = h.index[-1] if len(h.index) else pd.Timestamp.now(tz=NY)
        start = (pd.Timestamp(year=last.year, month=1, day=1, tz=last.tz) if rng == "YTD"
                 else last.normalize() - pd.DateOffset(**RANGE_START[rng]))
        before = h.index[h.index <= start]
        if len(before):     # start from the last close on or before that date, the same base the rest of the app measures from
            start = before[-1]
        keep = h.index >= start
        h = h[keep]
        ma = {str(n): [None if v != v else round(float(v), 4) for v in a[keep].tolist()] for n, a in avgs.items()}
    else:
        # 1D includes pre-market and after hours, like Yahoo's day chart; only the latest day is kept
        h = tk.history(period=period, interval=interval, auto_adjust=True, prepost=rng == "1D").dropna(subset=["Close"])
        if rng == "1D" and len(h.index):
            h = h[h.index.tz_convert(NY).date == h.index[-1].tz_convert(NY).date()]
    pts = [[int(ts.timestamp()), round(float(c), 4), int(v) if v == v else 0]
           for ts, c, v in zip(h.index, h["Close"].tolist(), h["Volume"].tolist())]
    prev, day = None, None
    if rng == "1D":
        md = tk.history_metadata or {}
        prev = md.get("chartPreviousClose") or md.get("previousClose")
        if pts:
            d = h.index[-1].tz_convert(NY)
            at = lambda hh, mm: int(d.replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp())
            reg = h[(h.index >= pd.Timestamp(at(9, 30), unit="s", tz="UTC")) & (h.index < pd.Timestamp(at(16, 0), unit="s", tz="UTC"))]
            day = {"pre": at(4, 0), "open": at(9, 30), "close": at(16, 0), "post": at(20, 0),
                   "last": jsonable(md.get("regularMarketPrice")),   # the official regular-session price
                   # the day's basics for the stock page's key stats (regular session only, like Yahoo's quote page)
                   "o": jsonable(round(float(reg["Open"].iloc[0]), 4)) if len(reg) else None,
                   "hi": jsonable(md.get("regularMarketDayHigh")), "lo": jsonable(md.get("regularMarketDayLow")),
                   "vol": jsonable(md.get("regularMarketVolume"))}
    if not pts:
        raise ValueError("no bars")
    return {"pts": pts, "intraday": interval.endswith("m"), "interval": interval, "prevClose": jsonable(prev), "ma": ma, "day": day}


def market_open(now_ny=None):
    """Regular hours on a trading day, plus five minutes for the closing prints. Holidays and 1 pm early closes count."""
    now_ny = now_ny or dt.datetime.now(NY)
    hours = X.session_hours(now_ny.date())
    if not hours:
        return False
    close = (dt.datetime.combine(now_ny.date(), hours[1]) + dt.timedelta(minutes=5)).time()
    return hours[0] <= now_ny.time() <= close


def chart_ttl(rng):
    if rng in ("1D", "5D"):
        return 60 if market_open() or ext_session(dt.datetime.now(NY)) else 30 * 60
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
            return {}        # Yahoo answered: no date is scheduled (funds, or a company that hasn't announced one)
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


# ---------------------------------------------------------------- momentum signals (Screener)
SIGNALS_PATH = CACHE / "signals.json"
SIGNAL_FUNDS = ("SPY", "QQQ", "SMH")   # the S&P 500, the Nasdaq-100 and chip stocks; small caps would double the scan
SIG = {"running": False, "done": 0, "total": 0, "at": 0.0, "asOf": None, "rows": [], "error": None, "whileOpen": False}
_sig_lock = threading.Lock()


def _load_signals():
    try:
        SIG.update(json.loads(SIGNALS_PATH.read_text()), running=False)
    except Exception:
        pass


def _signal_ohlc(syms, start, done=None):
    """Daily bars for many symbols, in batches like download_closes. Returns {sym: DataFrame}."""
    out, todo = {}, list(syms)
    for attempt in range(2):
        missing = []
        for i in range(0, len(todo), 50):
            batch = todo[i:i + 50]
            try:
                df = yf.download(batch, start=start, auto_adjust=True, progress=False, threads=4, group_by="ticker")
                for t in batch:
                    try:
                        f = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                        f = f.dropna(subset=["Close"])
                    except Exception:
                        f = None
                    if f is not None and len(f) > 200:
                        out[t] = f
                    else:
                        missing.append(t)
            except Exception as e:
                log(f"signal bars batch failed: {e!r}")
                missing += batch
            if done:
                done(len(out))
        todo = missing
        if not todo:
            break
        time.sleep(3)
    return out


def signals_scan():
    """Score every stock in the big funds plus the person's own with the AlphaLens method. About a minute."""
    with S.lock:
        chips = {h["t"] for h in S.holdings.get("SMH", {}).get("holdings", [])}
        fund = {h["t"]: h.get("n") for f in SIGNAL_FUNDS for h in S.holdings.get(f, {}).get("holdings", [])}
        names, sectors = dict(S.names), dict(S.sectors)
    own = [t for t in personal.all_symbols() if t not in fund]
    etf_of = {k: (e, n) for e, n, k in X.SECTOR_ETFS}
    universe = [t for t in list(fund) + own if VALID.fullmatch(t) and t not in FUNDS and t not in etf_of]
    bench = ["SPY", "SMH"] + [e for e, _, _ in X.SECTOR_ETFS]
    SIG.update(running=True, done=0, total=len(universe))
    start = (dt.date.today() - dt.timedelta(days=430)).isoformat()
    try:
        _yf_fresh()
        b = _signal_ohlc(bench, start)
        if "SPY" not in b:
            raise RuntimeError("no S&P 500 prices")
        bars = _signal_ohlc(universe, start, done=lambda n: SIG.update(done=n))
        now_ny = dt.datetime.now(NY)
        today = now_ny.strftime("%Y-%m-%d")
        live = market_open(now_ny)
        trim = (lambda f: f[f.index.strftime("%Y-%m-%d") < today]) if live else (lambda f: f)   # score finished sessions only
        spy = trim(b["SPY"])["Close"]
        rows = []
        for t in universe:
            f = bars.get(t)
            if f is None:
                continue
            f = trim(f)
            if t in chips:
                sec = ("SMH", "Chip stocks (SMH)")
            else:
                sec = etf_of.get(str(sectors.get(t) or "").lower().replace(" ", "-"))
                sec = sec and (sec[0], f"{sec[1]} ({sec[0]})")
            sc = sec and b.get(sec[0])
            try:
                r = signals.score(f, spy, trim(sc)["Close"] if sc is not None else None, sec[1] if sec else None)
            except Exception as e:
                log(f"signals {t} failed: {e!r}")
                continue
            if r:
                rows.append({"t": t, "n": fund.get(t) or names.get(t) or t, "fund": t in fund,
                             "sector": sectors.get(t), "vs": sec[0] if sec else None, **r})
        rows.sort(key=lambda r: (signals.ORDER.index(r["rating"]), -r["score"]))
        as_of = spy.index[-1].strftime("%Y-%m-%d")
        partial = sum(1 for r in rows if r["vs"]) < 0.8 * len(rows)   # sectors still being looked up on a first launch
        SIG.update(rows=jsonable(rows), asOf=as_of, at=time.time(), whileOpen=live, partial=partial, running=False, error=None)
        SIGNALS_PATH.write_text(json.dumps({k: SIG[k] for k in ("rows", "asOf", "at", "whileOpen", "partial")}, separators=(",", ":")))
        log(f"signals: scored {len(rows)}/{len(universe)} stocks as of {as_of}")
    except Exception as e:
        log(f"signals scan failed: {e!r}")
        SIG.update(running=False, failAt=time.time(), error="Yahoo didn't send price history just now. Trying again shortly.")
    finally:
        SIG["running"] = False


def signals_payload(private):
    """The latest scores; starts a fresh scan in the background when a new close is out (or every six hours)."""
    age = time.time() - SIG["at"]
    stale = not SIG["rows"] or age > 6 * 3600 or SIG["whileOpen"] and not market_open() or SIG.get("partial") and age > 900
    stale = stale and bool(S.holdings.get("SPY"))   # the first launch is still fetching what the funds hold
    with _sig_lock:
        if stale and not SIG["running"] and time.time() - SIG.get("failAt", 0) > 300:
            SIG["running"] = True
            threading.Thread(target=signals_scan, daemon=True).start()
    rows = SIG["rows"] if private else [r for r in SIG["rows"] if r.get("fund")]
    return {"rows": rows, "asOf": SIG["asOf"], "at": SIG["at"] or None, "running": SIG["running"],
            "done": SIG["done"], "total": SIG["total"], "error": SIG["error"], "funds": list(SIGNAL_FUNDS)}


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
                        e = ticker_earnings(t)
                        if e:
                            got[t] = e
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


_SUFFIX = re.compile(r"[\s,]+(Inc|Corp|Corporation|Co|Cos|Company|Ltd|Plc|Lp|Nv|Sa|Ag|Holdings Inc)\.?$", re.I)


def nice_name(n):
    """'Costco Wholesale Corporation' -> 'Costco Wholesale', 'Procter + Gamble Co/The' -> 'Procter & Gamble', as the app shows them."""
    n = re.sub(r"\s*\+\s*", " & ", re.sub(r"\s+", " ", str(n or "")).strip()).replace("/The", "")
    m = re.search(r"\s+(?:Cl|Class)\s+([A-C])$", n)
    cls = f" Class {m.group(1)}" if m else ""
    n = n[:m.start()] if m else n
    for _ in range(3):
        n = _SUFFIX.sub("", n)
    n = re.sub(r"\s*&$", "", n)
    if n.isupper() and len(n) > 5:
        n = n.title()
    n = {"Jpmorgan Chase & Co": "JPMorgan Chase", "Jpmorgan Chase": "JPMorgan Chase", "Nvidia": "NVIDIA", "Amazon.Com": "Amazon.com"}.get(n, n)
    return n + cls


def symbol_names():
    names = {}
    for f in FUNDS:
        for h in S.holdings.get(f, {}).get("holdings", []):
            names.setdefault(h["t"], h["n"])
    for t, n in S.names.items():
        names.setdefault(t, n)
    for (kind, *rest), (_, val) in list(_detail_cache.items()):
        if kind == "info" and isinstance(val, dict) and val.get("longName"):
            names[rest[0]] = val["longName"]
    return {t: nice_name(n) for t, n in names.items()}


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
    if not pair:
        return None
    word = {"Financials": "financial", "Industrials": "industrial", "Utilities": "utility", "Technology": "tech"}.get(etf[1], etf[1].lower())
    return (f"{word} stocks", pair, etf[0])


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
            hours = X.session_hours(now.date())     # None on weekends and market holidays; 1 pm on early-close days
            after = hours and now >= dt.datetime.combine(now.date(), hours[1], tzinfo=NY) + dt.timedelta(minutes=15)
            if after and S.dates and S.dates[-1] == day:
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
    out["links"] = [links.public(l) for l in personal.links(uid)]
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
    wb = workbench.state
    rows.append({"name": "Tick's workbench", "detail": {"ready": "ready", "building": "setting up its Python toolbox",
                 "failed": f"its Python toolbox didn't install ({wb['why'] or 'no reason given'}); trying again within the hour"}
                 .get(wb["toolbox"], "not set up yet") + ("" if wb["claude_ok"] else "; Claude Code answers without it for now, "
                 "because its sandbox didn't start"), "ok": wb["toolbox"] != "failed" and wb["claude_ok"]})
    return {"ok": not problems, "rows": rows, "problems": problems, "checked": now}


def _quiet(fn):
    """A nice-to-have part of a response: if it fails, leave it out rather than fail the whole thing."""
    try:
        return fn()
    except Exception:
        return None


def _live_ttl(open_ttl, closed_ttl):
    return open_ttl if market_open() else closed_ttl


LEVEL_INDEXES = {"^GSPC", "^NDX", "^IXIC", "^DJI", "^RUT", "^VIX"}   # indexes the Levels page can chart besides tickers

EXTRA = {
    # name: (needs ticker, ttl seconds, function(sym, query))
    "analysts":   (True,  6 * 3600,  lambda s, q: X.analysts(s)),
    "financials": (True,  24 * 3600, lambda s, q: X.financials(s)),
    "ownership":  (True,  12 * 3600, lambda s, q: X.ownership(s)),
    "options":    (True,  None,      lambda s, q: X.options(s, _upcoming_earnings(s), (q.get("exp") or [None])[0])),
    "events":     (True,  24 * 3600, lambda s, q: X.events(s)),
    "ohlc":       (True,  None,      lambda s, q: X.ohlc(s)),
    "levels":     (True,  None,      lambda s, q: X.levels(s, (q.get("iv") or ["1d"])[0])),
    "etf":        (True,  24 * 3600, lambda s, q: X.etf(s)),
    "macro":      (False, None,      lambda s, q: {"daily": cached(("macro-daily",), 1800, X.macro_daily),
                                                   "intraday": cached(("macro-intra",), _live_ttl(60, 1800), X.macro_intraday),
                                                   "status": cached(("mstatus",), 300, X.market_status),
                                                   "overnight": None if market_open() else _quiet(lambda: cached(
                                                       ("overnight",), 60 if X.futures_trading() else 1800, X.futures_overnight)),
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
        if not (VALID.fullmatch(sym) or name == "levels" and sym in LEVEL_INDEXES):
            raise ValueError("bad symbol")
    if name == "options":
        ttl = _live_ttl(600, 3 * 3600)
    if name == "ohlc":
        ttl = _live_ttl(300, 6 * 3600)
    if name == "levels":       # a 5-minute chart goes stale in a minute, a quarterly one in a day
        iv = (q.get("iv") or ["1d"])[0]
        ttl = {"5m": _live_ttl(60, 3600), "15m": _live_ttl(120, 3600), "1h": _live_ttl(300, 3600),
               "1wk": 6 * 3600, "3mo": 24 * 3600}.get(iv, _live_ttl(300, 6 * 3600))
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
                          "head": ("Price target " + ("raised" if ups else "cut") if len(pts) == 1 else
                                   (f"{len(ups)} price target raise{'s' if len(ups) != 1 else ''}" if ups else "")
                                   + (" and " if ups and dn else "") + (f"{dn} cut{'s' if dn != 1 else ''}" if dn else "")),
                          "text": (f"{avg * 100:+.0f}% to ${pts[0]['pt']:,.0f}, by {pts[0].get('firm')}" if len(pts) == 1 else
                                   f"in two weeks, {avg * 100:+.0f}% on average. Latest: {pts[0].get('firm')} to ${pts[0]['pt']:,.0f}"),
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

    def private_ok(self):
        """The person's own data (watchlist, positions, alerts, brief, Tick's data commands) answers only this Mac or a
        paired phone, the same rule as Tick. With phone access on, anyone else on the Wi-Fi sees market data only."""
        if agent.may_ask(self):
            return True
        self.send(403, json.dumps({"error": "Pair this phone first: on your Mac, open Settings, Your phone, QR code.", "pair": True}).encode(),
                  "application/json")
        return False

    def do_POST(self):
        # JSON only: a cross-site form can't send application/json without a CORS preflight we never allow
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, b"json only", "text/plain")
        if self.path.split("?")[0].startswith("/api/me/") and not self.private_ok():
            return
        if self.path.split("?")[0].startswith("/api/me/links/"):
            return self.links_post(self.path.split("?")[0][14:])
        if self.path.split("?")[0] == "/api/ask":
            return self.ask()
        if self.path.split("?")[0] == "/api/ask/stop":
            if not agent.may_ask(self):
                return self.send(403, b'{"error":"not allowed"}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
            except Exception:
                return self.send(400, b"bad json", "text/plain")
            return self.send(200, json.dumps({"ok": runs.stop(str(body.get("id") or ""), user_for(self))}).encode(), "application/json")
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

        def sym(raw=None):
            t = yahoo_symbol(str((body.get("t") if raw is None else raw) or ""))
            if not VALID.fullmatch(t):
                raise ValueError(f"{t or 'That'} isn't a ticker symbol." if raw is not None else "That isn't a ticker symbol.")
            if t not in S.px and not S.track(t):
                raise ValueError(f"Couldn't find prices for {t}.")
            return t

        def lot(r, label):
            """Shares, cost per share and date from one row of the positions editor, checked."""
            try:
                shares, cost = float(r.get("shares")), float(r.get("cost"))
            except (TypeError, ValueError):
                raise ValueError(f"{label}: shares and cost per share need numbers.")
            if not (math.isfinite(shares) and math.isfinite(cost)) or shares <= 0 or shares >= 1e12 or cost < 0 or cost >= 1e9:
                raise ValueError(f"{label}: shares must be above zero and cost can't be negative.")
            opened = str(r.get("opened") or "")[:10]
            if opened and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", opened):
                raise ValueError(f"{label}: the date should look like 2024-03-15.")
            return shares, cost, opened

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
            elif path == "/api/me/watch/save":
                add, remove = body.get("add") or [], body.get("remove") or []
                if not isinstance(add, list) or not isinstance(remove, list) or len(add) + len(remove) > 500:
                    raise ValueError("Nothing to save.")
                add = list(dict.fromkeys(sym(t) for t in add))
                remove = [yahoo_symbol(str(t)) for t in remove]
                personal.save_watch(uid, add, [t for t in remove if t not in add])
            elif path == "/api/me/positions/save":
                rows, dele = body.get("lots") or [], body.get("delete") or []
                if not isinstance(rows, list) or not isinstance(dele, list) or len(rows) + len(dele) > 1000:
                    raise ValueError("Nothing to save.")
                mine = {p["id"] for p in personal.positions(uid)}
                upd, add = [], []
                for r in rows:
                    r = r if isinstance(r, dict) else {}
                    if r.get("id"):
                        if int(r["id"]) not in mine:
                            raise ValueError("A position changed while you were editing. Close and open the editor again.")
                        upd.append((int(r["id"]), *lot(r, str(r.get("t") or "A position"))))
                    else:
                        t = sym(r.get("t") or "")
                        add.append((t, *lot(r, t)))
                personal.save_positions(uid, upd, add, [int(i) for i in dele if int(i) in mine])
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

    # ------------------------------------------------------------ linked accounts (links.py)
    def links_post(self, action):
        """Connect, review, sync and disconnect brokerages. Adding or removing a sign-in answers only this Mac."""
        if action in ("connect", "reconnect", "disconnect", "cancel") and not (agent.is_local(self) and agent.host_ok(self)):
            return self.send(403, json.dumps({"error": "Connect and disconnect accounts on the Mac that runs OpenTicker."}).encode(), "application/json")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 20_000)) or b"{}")
        except Exception:
            return self.send(400, b"bad json", "text/plain")
        uid, lid = user_for(self), str(body.get("id") or "")
        try:
            if action in ("connect", "reconnect"):
                out = links.connect(uid, str(body.get("provider") or ""), body.get("url"), body.get("name")) if action == "connect" \
                    else links.reconnect(uid, lid)
                out["opened"] = bool(out.get("auth_url")) and links.open_browser(out["auth_url"])
            elif action == "apply":
                off = body.get("off")
                out = {"count": links.apply(uid, lid, off if isinstance(off, list) else None, drop_mine=bool(body.get("drop_mine")))}
            elif action == "sync":
                ids = [lid] if lid else [l["id"] for l in personal.links(uid) if l["status"] == "ok"]
                out, errs = {"count": 0}, []
                for i in ids:   # one account failing doesn't stop the others
                    try:
                        out["count"] += links.sync(uid, i)
                    except ValueError as e:
                        errs.append(str(e))
                if errs and len(errs) == len(ids):
                    raise ValueError(errs[0])
                out["errors"] = errs
            elif action == "retry":
                links.retry(uid, lid)
                out = {}
            elif action == "disconnect":
                links.disconnect(uid, lid, keep=bool(body.get("keep")))
                out = {}
            elif action == "cancel":
                links.cancel(uid, lid)
                out = {}
            else:
                return self.send(404, b"not found", "text/plain")
        except (ValueError, links.M.MCPError, RuntimeError) as e:
            return self.send(400, json.dumps({"error": links._msg(e)}).encode(), "application/json")
        out["me"] = me_payload(uid)
        self.send(200, json.dumps(jsonable(out)).encode(), "application/json")

    def links_callback(self):
        """The browser comes back here from Monarch's, IBKR's or Robinhood's sign-in page, on this Mac only."""
        if not (agent.is_local(self) and agent.host_ok(self)):
            return self.send(403, b"Only on the Mac that runs OpenTicker.", "text/plain")
        ok, msg = links.callback(parse_qs(urlsplit(self.path).query))
        page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenTicker</title><style>:root{{color-scheme:light dark;--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--ok:#15803d;--bad:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0c0a09;--fg:#f5f5f4;--mut:#a8a29e;--ok:#4ade80;--bad:#f87171}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}}
main{{max-width:360px;padding:24px;text-align:center}}b{{display:block;font-size:18px;margin-bottom:6px;color:var({"--ok" if ok else "--bad"})}}p{{margin:0;color:var(--mut)}}</style>
<main><b>{"Connected" if ok else "Not connected"}</b><p>{html.escape(msg)} {"Go back to OpenTicker to choose what to add. You can close this tab." if ok else ""}</p></main>
<script>setTimeout(()=>window.close(),{2500 if ok else 60000})</script>"""
        self.send(200, page.encode(), "text/html; charset=utf-8")

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
        fit = None if sk else agent.match_skill(q, scope)   # a typed question a playbook says it covers
        spec = {"q": q, "skill": sk["name"] if sk else fit["name"] if fit else None, "history": hist, "model": body.get("model"), "effort": body.get("effort"),
                "scope": scope, "t": t or None}
        rid = runs.start(uid, cid, prov, spec, lambda: agent.context_for(scope, t, uid))
        self.follow_run(rid, uid, 0)   # the answer runs on its own: leaving this stream doesn't stop it

    def follow_run(self, rid, uid, after):
        """Stream a run's log as Server-Sent Events: what's there after `after`, then the rest as it comes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        state = {"alive": True}

        def write(seq, kind, payload):
            if not state["alive"]:
                return
            try:
                self.wfile.write(((f"id: {seq}\n" if seq else "") + f"event: {kind}\ndata: {json.dumps(payload)}\n\n").encode())
                self.wfile.flush()
            except Exception:
                state["alive"] = False
        if not runs.follow(rid, uid, after, write, lambda: state["alive"]):
            write(None, "gone", {})

    def do_GET(self):
        path = self.path.split("?")[0]
        if (path in ("/api/me", "/api/me/close-note", "/api/brief", "/api/me/links") or path.startswith("/api/agent/")) and not self.private_ok():
            return
        if path == "/api/links/callback":
            return self.links_callback()
        if path == "/api/me/links":
            uid, qs = user_for(self), parse_qs(urlsplit(self.path).query)
            lid = (qs.get("preview") or [""])[0]
            body = {"links": [links.public(l) for l in personal.links(uid)], "presets": links.presets(),
                    "local": agent.is_local(self) and agent.host_ok(self)}
            if lid:
                body["preview"] = links.preview(uid, lid)
            return self.send(200, json.dumps(jsonable(body)).encode(), "application/json")
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
        elif path == "/api/ask/run":
            if not agent.may_ask(self):
                return self.send(403, b'{"error":"not allowed"}', "application/json")
            qs = parse_qs(urlsplit(self.path).query)
            rid, after = (qs.get("id") or [""])[0], (qs.get("after") or ["0"])[0]
            if not re.fullmatch(r"[0-9a-f]{16}", rid) or not after.isdigit():
                return self.send(400, b'{"error":"bad run"}', "application/json")
            self.follow_run(rid, user_for(self), int(after))
        elif path == "/api/ask/file":
            # a chart or file Tick's code saved in its workbench (see workbench.py); <img> can't send headers, so the
            # phone's token may come in the query too
            qs = parse_qs(urlsplit(self.path).query)
            k = (qs.get("k") or [""])[0]
            if not (agent.may_ask(self) or (agent.host_ok(self) and k and secrets.compare_digest(k, agent.pair_token()))):
                return self.send(403, b'{"error":"not allowed"}', "application/json")
            cid, name = (qs.get("chat") or [""])[0], (qs.get("name") or [""])[0]
            f = workbench.file_path(cid, name) if personal.chat(user_for(self), cid) else None
            if not f:
                return self.send(404, b'{"error":"not found"}', "application/json")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            inline = ctype in ("image/png", "image/jpeg", "image/gif", "image/webp")
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype if inline or ctype.startswith("text/") and ctype != "text/html" else "application/octet-stream")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")   # never runs as a page on our origin
            self.send_header("X-Content-Type-Options", "nosniff")
            if not inline:
                self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
            self.send_header("Cache-Control", "private, max-age=60")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path in ("/api/ask/chats", "/api/ask/chat"):
            if not agent.may_ask(self):
                return self.send(403, b'{"error":"not allowed"}', "application/json")
            uid = user_for(self)
            if path.endswith("chats"):
                body = personal.chats(uid)
            else:
                cid = (parse_qs(urlsplit(self.path).query).get("id") or [""])[0]
                body = personal.chat(uid, cid) or {"error": "not found"}
                if "error" not in body:
                    body["running"] = runs.running_for_chat(uid, cid)   # an answer still being written: the page reattaches
            self.send(200, json.dumps(body).encode(), "application/json")
        elif path == "/api/brief":
            self.send(200, json.dumps(brief(user_for(self))).encode(), "application/json")
        elif path == "/api/me":
            self.send(200, json.dumps(me_payload(user_for(self))).encode(), "application/json")
        elif path == "/api/me/close-note":
            self.send(200, json.dumps(jsonable(close_note(user_for(self)) or {})).encode(), "application/json")
        elif path == "/api/signals":
            self.send(200, json.dumps(signals_payload(agent.may_ask(self)), separators=(",", ":")).encode(), "application/json")
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
    links.bind(sys.modules[__name__])
    runs.recover()
    workbench.ensure()
    workbench.state["serve"] = (PORT, agent.AGENT_CMDS)
    # Serve right away: from the last run's prices if there are any, otherwise a loading screen that says what's
    # happening. Fresh holdings and history download behind it, then the background loops start.
    S.load_cache()
    _load_signals()
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
        threading.Thread(target=ext_loop, daemon=True).start()
        threading.Thread(target=sector_loop, daemon=True).start()
        threading.Thread(target=links.loop, daemon=True).start()

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
