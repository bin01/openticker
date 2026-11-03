"""Where OpenTicker keeps things.

Code and web assets live next to this file. Your data (watchlist, positions, alerts, caches) lives in
OPENTICKER_HOME, by default ~/Library/Application Support/OpenTicker on a Mac, so updating the code never
touches it. A checkout that already has data/app.db beside the code keeps using it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent


def _home() -> Path:
    env = os.environ.get("OPENTICKER_HOME")
    if env:
        return Path(env).expanduser()
    if (APP / "data" / "app.db").exists():
        return APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenTicker"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "openticker"


def _first(*cands: Path) -> Path:
    return next((c for c in cands if c.exists()), cands[-1])


HOME = _home()
CACHE = HOME / "cache"
DATA = HOME / "data"
LOGS = HOME / "logs"
for _d in (CACHE, DATA, LOGS):
    _d.mkdir(parents=True, exist_ok=True)
SKILLS = _first(APP / "skills", ROOT / "skills")
BIN = _first(APP / "bin", ROOT / "bin")
