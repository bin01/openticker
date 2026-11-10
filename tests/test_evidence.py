"""The evidence features: the momentum score's track record never looks ahead, breadth counts the right stocks, an
evidence check's verdict block is checked before it's kept, kept once per stock and day, and looked back on with the
prices since. Playbooks can name the sections they read. Nothing here touches the network."""
import os
import re
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OPENTICKER_HOME", tempfile.mkdtemp(prefix="ot-test-"))
sys.path.insert(0, str(ROOT / "app"))
import agent  # noqa: E402
import personal  # noqa: E402
import signals  # noqa: E402


def bars(path):
    idx = pd.bdate_range("2024-01-01", periods=len(path))
    c = pd.Series(path, index=idx, dtype=float)
    up = c.diff().fillna(0) > 0
    return pd.DataFrame({"High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": np.where(up, 1.5e6, 1e6)}, index=idx)


def walk(n, drift, seed):
    rng = np.random.default_rng(seed)
    return 50 * np.cumprod(1 + rng.normal(drift, 0.012, n))


class TrackRecord(unittest.TestCase):
    def setUp(self):
        n = 420
        self.spy = pd.Series(walk(n, 0.0004, 1) * 8, index=pd.bdate_range("2024-01-01", periods=n))
        self.up, self.down = bars(walk(n, 0.002, 2)), bars(walk(n, -0.002, 3))

    def test_no_look_ahead(self):
        """Changing what happens after a date leaves the rating on that date alone."""
        a = signals.track({"X": self.up}, self.spy, step=20)["X"]
        later = self.up.copy()
        later.iloc[-60:] *= 0.5
        b = signals.track({"X": later}, self.spy, step=20)["X"]
        cut = later.index[-61].strftime("%Y-%m-%d")
        old_a = [r[:3] for r in a if r[0] <= cut]
        old_b = [r[:3] for r in b if r[0] <= cut]
        self.assertTrue(old_a)
        self.assertEqual(old_a, old_b)

    def test_rows_and_returns(self):
        rows = signals.track({"X": self.up}, self.spy, step=10)["X"]
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))       # oldest first
        self.assertEqual(rows[-1][0], self.up.index[-1].strftime("%Y-%m-%d"))    # ends today
        self.assertIsNone(rows[-1][4])                                           # today's result isn't known yet
        first = rows[0]
        i = list(self.up.index.strftime("%Y-%m-%d")).index(first[0])
        want = self.up["Close"].iloc[i + 21] / self.up["Close"].iloc[i] - 1
        self.assertAlmostEqual(first[4], want, places=3)
        self.assertIn(first[1], signals.ORDER)

    def test_summary(self):
        st = signals.track({"U": self.up, "D": self.down}, self.spy, step=10)
        sm = signals.track_summary(st)
        self.assertEqual(sm["stocks"], 2)
        known = sum(1 for v in st.values() for r in v if r[4] is not None)
        self.assertEqual(sm["ratings"]["All"]["21"]["n"], known)
        self.assertEqual(sum(sm["ratings"][k]["21"].get("n", 0) for k in signals.ORDER), known)
        a = sm["ratings"]["All"]["21"]
        self.assertTrue(0 <= a["beat"] <= 1)

    def test_breadth(self):
        b = signals.breadth({"U": self.up, "D": self.down})
        self.assertEqual(b["n"], 2)
        self.assertEqual(b["above200"], 0.5)   # the climber is above its 200-day, the slider below


class Reads(unittest.TestCase):
    def setUp(self):
        self.old = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        px = {"NVDA": [100.0, 110.0], "SPY": [500.0, 505.0]}
        S = types.SimpleNamespace(lock=threading.Lock(), dates=["2026-11-09", "2026-11-10"], px=px)
        X = types.SimpleNamespace(ny_today=lambda: __import__("datetime").date(2026, 11, 10))
        from zoneinfo import ZoneInfo
        self.srv = types.SimpleNamespace(S=S, X=X, personal=personal, NY=ZoneInfo("America/New_York"), VALID=re.compile(r"[A-Z0-9.\-^=]{1,12}"),
                                         yahoo_symbol=lambda t: t.upper(), TRACK={"stocks": {}})
        self.bind = mock.patch.object(agent, "srv", self.srv)
        self.bind.start()

    def tearDown(self):
        self.bind.stop()
        personal._conn.close()
        personal._conn = self.old

    def answer(self, **v):
        import json
        body = {"t": "NVDA", "lean": "positive", "for": 4, "against": 1, "neutral": 1, "line": "Trend and estimates agree."}
        body.update(v)
        return "Leans positive.\n\n```verdict\n" + json.dumps(body) + "\n```\n"

    def test_verdict_checked(self):
        self.assertEqual(agent.verdict_in(self.answer())["for"], 4)
        self.assertIsNone(agent.verdict_in(self.answer(lean="buy")))
        self.assertIsNone(agent.verdict_in(self.answer(t="rm -rf /")))
        self.assertIsNone(agent.verdict_in(self.answer(against=99)))
        self.assertIsNone(agent.verdict_in("no block here"))
        self.assertIsNone(agent.verdict_in("```verdict\n{not json\n```"))

    def test_kept_once_a_day_for_the_stock_asked(self):
        self.assertIsNone(agent.record_verdict("me", {"t": "AAPL"}, self.answer()))    # a verdict about another stock
        agent.record_verdict("me", {"t": "NVDA"}, self.answer())
        agent.record_verdict("me", {"t": "NVDA"}, self.answer(lean="mixed", against=2, neutral=0))
        rows = personal.reads("me", "NVDA")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["lean"], rows[0]["price"], rows[0]["spy"]), ("mixed", 110.0, 505.0))

    def test_looked_back_on(self):
        personal.read_add("me", "NVDA", "positive", 4, 1, 1, "Trend and estimates agree.", 100.0, 500.0, "2026-10-01")
        out = agent.reads_context("me", "NVDA")
        self.assertIn("+10.0%", out)    # the stock since
        self.assertIn("+1.0%", out)     # the S&P 500 since
        self.assertIn("+9.0%", out)     # the lead
        self.assertIn("Checks at least four weeks old: positive ones led the S&P 500 by +9.0%", out)

        self.assertIn("No evidence checks yet", agent.reads_context("me", "AMD"))
        personal.read_add("me", "SPY", "negative", 1, 4, 1, "", 500.0, 500.0, "2026-11-09")
        self.assertNotIn("negative ones", agent.reads_context("me"))   # a day old: too soon to count
        with self.assertRaises(ValueError):
            personal.read_add("me", "NVDA", "buy", 1, 1, 1, "", 1.0, 1.0, "2026-10-02")


class PlaybookData(unittest.TestCase):
    def test_new_playbooks(self):
        self.assertEqual(agent.skill("weigh-evidence")["data"], ["signals", "valuation"])
        self.assertEqual(agent.skill("position-review")["data"], ["signals", "technicals"])
        for s in agent.skills():
            self.assertLessEqual(set(s["data"]), set(agent.SECTIONS), s["name"])

    def test_typed_questions(self):
        m = lambda q: (agent.match_skill(q, "stock") or {}).get("name")
        self.assertEqual(m("Should I buy NVDA here?"), "weigh-evidence")
        self.assertEqual(m("should I sell my NVDA shares?"), "position-review")
        self.assertEqual(m("time to trim my position in AAPL?"), "position-review")
        self.assertIsNone(m("review my portfolio"))

    def test_context_carries_the_playbooks_sections(self):
        calls = []
        with mock.patch.object(agent, "stock_context", side_effect=lambda t, uid, only=None: calls.append(only) or "x"):
            agent.context_for("stock", "NVDA", "me", "weigh-evidence")
            agent.context_for("stock", "NVDA", "me", "stock-snapshot")
        self.assertEqual(calls, [None, ["signals", "valuation"], None])

    def test_agents_may_run_the_new_commands(self):
        for c in ("signals", "valuation", "reads"):
            self.assertIn(c, agent.AGENT_CMDS)
            self.assertIn(c, agent.TOOLS_NOTE)


if __name__ == "__main__":
    unittest.main()
