"""OpenTicker's data for code Tick writes in its workbench. Reads files OpenTicker keeps on disk, so it works inside
the sandbox with no network. See app/workbench.py.

    import ot
    px = ot.prices(["NVDA", "SPY"])      # daily closes, dates down, tickers across
    r = ot.returns(["NVDA", "SPY"])      # daily returns
    ot.positions(), ot.watchlist()       # the person's own
    ot.style()                           # charts that match the app, in light and dark
    ot.get_json("https://data.sec.gov/submissions/CIK0001045810.json")   # web data, with a declared user agent
"""
import json
import os
import time
import urllib.parse
import urllib.request

# Sites like SEC EDGAR refuse the default user agents of Python libraries and ask automated tools to say who they are.
USER_AGENT = os.environ.get("OT_USER_AGENT") or "OpenTicker/0.1 (personal research tool; github.com/bin01/openticker; openticker@users.noreply.github.com)"
_last = {}

_cache = {}


def _load(name, env):
    p = os.environ.get(env) or ""
    if name not in _cache or _cache[name][0] != os.path.getmtime(p):
        with open(p) as f:
            _cache[name] = (os.path.getmtime(p), json.load(f))
    return _cache[name][1]


def tickers():
    """Every ticker with price history on hand."""
    return sorted(_load("px", "OT_PRICES")["px"])


def prices(tickers=None, start=None):
    """Daily closes as a pandas DataFrame. tickers: a list (or one string); None for all ~1,100. start: 'YYYY-MM-DD'."""
    import pandas as pd
    d = _load("px", "OT_PRICES")
    if isinstance(tickers, str):
        tickers = [tickers]
    want = [t.upper().replace(".", "-") for t in (tickers or d["px"])]
    missing = [t for t in want if t not in d["px"]]
    df = pd.DataFrame({t: d["px"][t] for t in want if t in d["px"]}, index=pd.to_datetime(d["dates"]), dtype=float)
    if missing:                       # not tracked by OpenTicker: fetch them from Yahoo for the same dates
        got = _yahoo(missing, df.index.min() if len(df.index) else None)
        still = [t for t in missing if t not in got]
        if still:
            raise KeyError(f"No price history for {', '.join(still)}: OpenTicker doesn't track them and Yahoo had nothing. "
                           "Check the ticker, or try yfinance directly.")
        df = df.join(got[missing], how="outer") if len(df.columns) else got[missing]
    df = df[want]
    df = df.where(df > 0)
    df.index.name = "date"
    return df.loc[start:] if start else df


def _yahoo(tickers, since):
    """Daily closes from Yahoo for tickers OpenTicker doesn't keep, over the network (through the workbench's proxy)."""
    import pandas as pd
    try:
        import yfinance as yf
        start = (since - pd.Timedelta(days=1)).strftime("%Y-%m-%d") if since is not None else None
        raw = yf.download(tickers, start=start, period=None if start else "2y", auto_adjust=False, progress=False, threads=False)
        px = raw["Close"] if "Close" in raw else raw
        if isinstance(px, pd.Series):
            px = px.to_frame(tickers[0])
        px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
        px.index.name = "date"
        return px[[c for c in px.columns if px[c].notna().any()]]
    except Exception:
        return pd.DataFrame()


def returns(tickers=None, start=None):
    """Daily returns of prices(...)."""
    return prices(tickers, start).pct_change(fill_method=None).iloc[1:]


def _you():
    p = os.path.join(os.environ.get("OT_WORKSPACE", "."), ".openticker", "you.json")
    try:
        with open(p) as f:
            return json.load(f)
    except OSError:
        return {}


def positions():
    """The person's positions as a DataFrame: t, shares, cost (per share), opened, note."""
    import pandas as pd
    return pd.DataFrame(_you().get("positions") or [], columns=["t", "shares", "cost", "opened", "note"])


def watchlist():
    return list(_you().get("watchlist") or [])


def get(url, headers=None, timeout=30):
    """A web page or file as text, fetched with OpenTicker's declared user agent. Paced to under 10 requests a second per
    site, which SEC asks for. Raises urllib.error.HTTPError (with .code) when the site says no."""
    return _fetch(url, headers, timeout).decode("utf-8", "replace")


def get_json(url, headers=None, timeout=30):
    """The same as get(), parsed as JSON."""
    return json.loads(_fetch(url, headers, timeout))


def _fetch(url, headers, timeout):
    host = urllib.parse.urlsplit(url).hostname or ""
    wait = _last.get(host, 0) + 0.12 - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def style():
    """Matplotlib settings that sit well in Tick's panel in light and dark: transparent, quiet grey text, thin lines."""
    import logging
    import matplotlib as mpl
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # fonts missing on this machine fall back quietly
    grey, grid = "#8a8f98", "#8a8f9840"
    mpl.rcParams.update({
        "figure.figsize": (7.2, 4), "figure.dpi": 100, "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.transparent": True,
        "figure.facecolor": "none", "axes.facecolor": "none", "font.size": 10.5, "font.family": ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "text.color": grey, "axes.labelcolor": grey, "xtick.color": grey, "ytick.color": grey, "axes.edgecolor": grid,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": grid, "grid.linewidth": 0.8,
        "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlecolor": grey, "axes.titlelocation": "left",
        "lines.linewidth": 1.8, "legend.frameon": False, "date.converter": "concise",
        "axes.prop_cycle": mpl.cycler(color=["#2fb877", "#5b8def", "#e8a33d", "#c45ec4", "#e5534b", "#8a8f98"]),
    })
