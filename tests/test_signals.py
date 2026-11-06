"""The momentum score on made-up price paths: a steady climb rates well, a slide rates Avoid, gates cap the rating."""
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import signals  # noqa: E402


def bars(path, vol_up=1.0):
    idx = pd.bdate_range("2025-06-02", periods=len(path))
    c = pd.Series(path, index=idx, dtype=float)
    up = c.diff().fillna(0) > 0
    return pd.DataFrame({"High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Volume": np.where(up, 1e6 * vol_up, 1e6)}, index=idx)


class SignalsTest(unittest.TestCase):
    def test_ratings_scale(self):
        assert signals.rating_for(10) == "Strong Buy" and signals.rating_for(7) == "Buy"
        assert signals.rating_for(4) == "Accumulate" and signals.rating_for(1) == "Hold" and signals.rating_for(0.75) == "Avoid"


    def test_uptrend_beats_downtrend(self):
        n = 320
        rng = np.random.default_rng(1)
        spy = pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.008, n)), index=pd.bdate_range("2025-06-02", periods=n))
        up = 50 * np.cumprod(1 + rng.normal(0.0025, 0.01, n))
        down = 50 * np.cumprod(1 + rng.normal(-0.0025, 0.01, n))
        a = signals.score(bars(up, 1.6), spy, spy, "Market (SPY)")
        b = signals.score(bars(down), spy, spy, "Market (SPY)")
        assert a["score"] > b["score"]
        assert b["rating"] in ("Avoid", "Hold") and a["rating"] in ("Strong Buy", "Buy", "Accumulate")
        assert a["stop"] < a["entry"] < a["target"]
        assert abs((a["target"] - a["entry"]) / (a["entry"] - a["stop"]) - 2.5) < 0.01
        assert {g["name"] for g in a["gates"]} == {"Trend strength (ADX)", "Weekly RSI"}
        assert len(a["signals"]["core"]) == 6 and len(a["signals"]["boost"]) == 6


    def test_gate_caps_rating(self):
        assert signals._cap("Strong Buy", "Hold") == "Hold"
        assert signals._cap("Avoid", "Hold") == "Avoid"
        assert signals._cap("Buy", "Accumulate") == "Accumulate"


    def test_short_history_is_skipped(self):
        spy = pd.Series(np.linspace(100, 110, 100), index=pd.bdate_range("2025-06-02", periods=100))
        assert signals.score(bars(np.linspace(10, 20, 100)), spy) is None


if __name__ == "__main__":
    unittest.main()
