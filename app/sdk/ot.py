"""OpenTicker's data for code Tick writes in its workbench. Reads files OpenTicker keeps on disk, so it works inside
the sandbox with no network. See app/workbench.py.

    import ot
    px = ot.prices(["NVDA", "SPY"])      # daily closes, dates down, tickers across
    r = ot.returns(["NVDA", "SPY"])      # daily returns
    ot.positions(), ot.watchlist()       # the person's own
    ot.style()                           # charts that match the app, in light and dark
"""
import json
import os

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
    if missing:
        raise KeyError(f"No price history on hand for {', '.join(missing)}. Run `openticker history {' '.join(missing)}` "
                       "once (it starts tracking them), or use yfinance.")
    df = pd.DataFrame({t: d["px"][t] for t in want}, index=pd.to_datetime(d["dates"]), dtype=float)
    df = df.where(df > 0)
    df.index.name = "date"
    return df.loc[start:] if start else df


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
