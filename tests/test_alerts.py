"""Checks the words that go out on their own: why a stock moved, the alerts that carry it, and the close note.
Uses an in-memory database, so the person's real alerts are never touched."""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import personal  # noqa: E402
import server  # noqa: E402


def calm(n=70, start=100.0, step=0.01):
    """A stock that moves exactly 1% a day, alternating up and down."""
    out, p = [], start
    for i in range(n):
        p *= 1 + (step if i % 2 else -step)
        out.append(round(p, 4))
    return out


class MoveReason(unittest.TestCase):
    def test_typical_move_is_the_median_daily_move(self):
        self.assertAlmostEqual(server.typical_move(calm() + [1]), 0.01, places=4)
        self.assertIsNone(server.typical_move([100, 101, 102]))       # too little history to say

    def test_own_news(self):
        a = calm() + [calm()[-1] * 0.94]                              # -6% on a quiet market
        r = server.move_reason("ABC", a, spy=[100, 100.2], peer=("chip stocks", [100, 100.1], "SMH"))
        self.assertEqual(r["who"], "own")
        self.assertAlmostEqual(r["size"], 6, delta=0.2)
        s = server.reason_sentence(r, live=False)
        self.assertIn("about 6× a normal day for ABC", s)
        self.assertIn("The S&P 500 closed up 0.2% and chip stocks (SMH) closed up 0.1%, so this move is about ABC itself.", s)

    def test_the_group_explains_it(self):
        a = calm() + [calm()[-1] * 0.95]
        r = server.move_reason("ABC", a, spy=[100, 99.7], peer=("chip stocks", [100, 95.8], "SMH"))
        self.assertEqual(r["who"], "group")
        self.assertIn("so most of this is the group", server.reason_sentence(r))
        self.assertEqual(server.reason_phrase(r), "5× a normal day, mostly chip stocks")

    def test_the_market_explains_it(self):
        a = calm() + [calm()[-1] * 0.97]
        r = server.move_reason("ABC", a, spy=[100, 97.5])
        self.assertEqual(r["who"], "market")
        self.assertIn("The S&P 500 is down 2.5%, so most of this is the whole market.", server.reason_sentence(r))

    def test_tiny_moves_get_no_verdict(self):
        a = calm() + [calm()[-1] * 1.002]
        r = server.move_reason("ABC", a, spy=[100, 100.1])
        self.assertIsNone(r["who"])
        self.assertNotIn("so ", server.reason_sentence(r))


class ExplainedAlerts(unittest.TestCase):
    def setUp(self):
        self.old = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        personal.set_watch("me", "ABC", True)
        self.pushed = []
        self.old_push = personal.push
        personal.push = lambda uid, title, body, **k: self.pushed.append((title, body))

    def tearDown(self):
        personal._conn.close()
        personal._conn = self.old
        personal.push = self.old_push

    def test_move_alert_says_why_once(self):
        a = calm() + [calm()[-1] * 0.93]
        calls = []

        def explain(t):
            calls.append(t)
            return "Because."
        args = ("me", {"ABC": a}, ["2026-11-03"], {"ABC": "ABC Corp"}, {})
        fired = personal.evaluate(*args, explain=explain)
        self.assertEqual(len(fired), 1)
        title, body = self.pushed[0]
        self.assertTrue(title.startswith("ABC −7.0% today"))
        self.assertTrue(body.endswith("on the day. Because."))
        self.assertEqual(personal.evaluate(*args, explain=explain), [])     # the same alert never fires twice...
        self.assertEqual(calls, ["ABC"])                                      # ...and isn't explained again


class CloseNote(unittest.TestCase):
    def setUp(self):
        self.old = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        self.saved = (server.S.dates, server.S.px, server.S.holdings, server.EARN)
        base = calm()
        server.S.dates = ["2026-11-02", "2026-11-03"]
        server.S.px = {"SPY": [100, 100.4], "QQQ": [100, 99.8], "SMH": [100, 100.1],
                       "ABC": base + [base[-1] * 1.08], "XYZ": base + [base[-1] * 0.995]}
        server.S.holdings = {}
        server.EARN = {"XYZ": {"date": "2026-11-04", "timing": "AMC", "reported": None}}

    def tearDown(self):
        personal._conn.close()
        personal._conn = self.old
        server.S.dates, server.S.px, server.S.holdings, server.EARN = self.saved

    def test_note(self):
        personal.set_watch("me", "XYZ", True)
        personal.add_position("me", "ABC", 10, 900)
        n = server.close_note("me", fetch=False)
        self.assertEqual(n["title"], "Market close: S&P 500 +0.40%, Nasdaq −0.20%")
        lines = n["body"].split("\n")
        self.assertTrue(lines[0].startswith("Your portfolio rose 8.0% (+$"))
        self.assertEqual(lines[1], "Your biggest movers: ABC +8.0% (8× a normal day, its own news).")   # XYZ is only watched
        self.assertEqual(lines[2], "Reporting tomorrow: XYZ after the close.")

    def test_watched_stocks_get_their_own_line(self):
        base = calm()
        server.S.px["WAT"] = base + [base[-1] * 0.95]
        personal.set_watch("me", "WAT", True)
        personal.add_position("me", "ABC", 10, 900)
        lines = server.close_note("me", fetch=False)["body"].split("\n")
        self.assertTrue(lines[1].startswith("Your biggest movers: ABC +8.0%"))
        self.assertNotIn("WAT", lines[1])
        self.assertTrue(lines[2].startswith("On your watchlist: WAT −5.0%"))

    def test_note_without_stocks_uses_the_index(self):
        server.S.holdings = {"SPY": {"holdings": [{"t": "ABC"}, {"t": "XYZ"}]}}
        n = server.close_note("me", fetch=False)
        self.assertTrue(n["body"].startswith("Biggest moves in the S&P 500: ABC +8.0%"))


if __name__ == "__main__":
    unittest.main()
