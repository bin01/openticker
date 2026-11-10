"""Assumptions the app used to rely on without checking (the audit of 2026-11-07): a refresh that comes back short,
a $0 cost, a zero close, a cut-off cache file, a loss-making company's estimates, a stale market price, half days and
the Mac's own date. Nothing here touches the network."""
import datetime as dt
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))
import agent  # noqa: E402
import paths  # noqa: E402
import personal  # noqa: E402
import server  # noqa: E402
import yahoo_extra as X  # noqa: E402

NY = ZoneInfo("America/New_York")


class Fresh(unittest.TestCase):
    """Each test gets its own database and price state."""
    def setUp(self):
        self.old_conn = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()
        S = server.S
        self.saved = (S.dates, S.px, S.history_fetched, S.version, S.holdings)
        S.dates, S.px = ["2026-11-05", "2026-11-06"], {"SPY": [680.0, 682.0], "AAPL": [270.0, 271.0], "MSFT": [500.0, 505.0]}
        self.p = [mock.patch.object(server, "session_closes", lambda *a, **k: {}),
                  mock.patch.object(server.S, "save_cache", lambda: None)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        personal._conn.close()
        personal._conn = self.old_conn
        S = server.S
        S.dates, S.px, S.history_fetched, S.version, S.holdings = self.saved


class Refresh(Fresh):
    def refresh(self, df):
        with mock.patch.object(server, "download_closes", lambda *a, **k: df):
            server.S.load_history()

    def test_offline_refresh_keeps_the_prices(self):
        self.refresh(pd.DataFrame())
        self.assertEqual(server.S.dates, ["2026-11-05", "2026-11-06"])
        self.assertEqual(server.S.px["AAPL"], [270.0, 271.0])
        self.assertLess(server.time.time() - server.S.history_fetched, server.HISTORY_TTL)   # looks again in a few minutes

    def test_a_fraction_of_symbols_is_ignored(self):
        self.refresh(pd.DataFrame({"SPY": [681.0]}, index=pd.to_datetime(["2026-11-06"])))
        self.assertEqual(server.S.px["SPY"], [680.0, 682.0])

    def test_skipped_symbols_keep_their_closes(self):
        df = pd.DataFrame({"SPY": [680.0, 682.0, 684.0], "MSFT": [500.0, 505.0, 510.0]},
                          index=pd.to_datetime(["2026-11-05", "2026-11-06", "2026-11-09"]))
        self.refresh(df)
        self.assertEqual(server.S.dates, ["2026-11-05", "2026-11-06", "2026-11-09"])
        self.assertEqual(server.S.px["AAPL"], [270.0, 271.0, 271.0])     # yesterday's close stands in for the new day
        self.assertEqual(server.S.px["MSFT"][-1], 510.0)

    def test_first_launch_with_nothing_is_an_error(self):
        server.S.dates, server.S.px = [], {}
        with self.assertRaises(RuntimeError):
            self.refresh(pd.DataFrame())


class ZeroCost(Fresh):
    def test_tick_still_gets_the_portfolio(self):
        personal.add_position("me", "AAPL", 10, 0.0)
        with mock.patch.object(server, "brief", lambda uid: {"items": []}), \
                mock.patch.object(agent, "srv", server):
            text = agent.portfolio_context("me")
            self.assertIn("AAPL", text)
            self.assertIn("n/a", text)
            self.assertIn("You own 10 shares", " ".join(agent._my_position("AAPL", "me")))

    def test_a_zero_close_doesnt_stop_alerts(self):
        personal.add_alert("me", "move", "MSFT", None, 1.0)
        personal.add_alert("me", "move", "AAPL", None, 1.0)
        with mock.patch.object(personal, "push", lambda *a, **k: True):
            fired = personal.evaluate("me", {"AAPL": [0.0, 271.0], "MSFT": [500.0, 520.0]}, ["2026-11-05", "2026-11-06"], {}, {})
        self.assertEqual([t for t, _, _ in fired], ["MSFT"])


class CacheFiles(unittest.TestCase):
    def test_write_is_whole_and_a_bad_file_reads_as_missing(self):
        d = Path(tempfile.mkdtemp())
        paths.write_json(d / "x.json", {"a": 1})
        self.assertEqual(paths.read_json(d / "x.json"), {"a": 1})
        self.assertEqual([p.name for p in d.iterdir()], ["x.json"])        # no temp file left behind
        (d / "x.json").write_text('{"a": ')
        self.assertEqual(paths.read_json(d / "x.json", {}), {})
        self.assertEqual(paths.read_json(d / "missing.json", {}), {})

    def test_server_starts_with_cut_off_caches(self):
        home = Path(tempfile.mkdtemp())
        (home / "cache").mkdir()
        for name in ("earnings.json", "sectors.json", "holdings.json", "names.json"):
            (home / "cache" / name).write_text('{"AAPL": {"date": "2026-')
        code = "import sys; sys.path.insert(0, %r); import server; print(server.EARN, server.S.sectors, server.load_holdings.__name__)" % str(APP)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"OPENTICKER_HOME": str(home), "PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stderr[-400:])


class Brief(Fresh):
    def test_a_loss_making_company_has_no_estimate_line(self):
        key = server._xkey("analysts", "LOSS")
        personal.set_watch("me", "LOSS", True)
        with mock.patch.dict(server._detail_cache, {key: (server.time.time(), {"eps_trend": {"0y": {"current": -0.5, "30daysAgo": -1.0}}})}), \
                mock.patch.object(server, "_brief_busy", mock.Mock(locked=lambda: True)):
            items = server.brief("me")["items"]
        self.assertFalse([i for i in items if i["kind"] == "estimates"])


class MarketToday(unittest.TestCase):
    def test_a_stale_intraday_price_isnt_today(self):
        macro = {"daily": {"dates": ["2026-11-05", "2026-11-06"], "px": {"^GSPC": [6800.0, 6830.0]}},
                 "intraday": {"last": {"^GSPC": 6700.0}, "day": {"^GSPC": "2026-10-30"}}}
        with mock.patch.object(server, "extra", lambda name, q: macro):
            self.assertEqual(server._macro_pair("^GSPC", "2026-11-06"), [6800.0, 6830.0])
            macro["intraday"]["day"]["^GSPC"] = "2026-11-06"
            self.assertEqual(server._macro_pair("^GSPC", "2026-11-06"), [6800.0, 6700.0])


class HalfDays(unittest.TestCase):
    def test_after_hours_starts_at_one_on_the_day_after_thanksgiving(self):
        self.assertEqual(server.ext_session(dt.datetime(2026, 11, 27, 13, 30, tzinfo=NY)), "post")
        self.assertIsNone(server.ext_session(dt.datetime(2026, 11, 27, 12, 30, tzinfo=NY)))
        self.assertEqual(server.ext_session(dt.datetime(2026, 11, 25, 16, 30, tzinfo=NY)), "post")
        self.assertIsNone(server.ext_session(dt.datetime(2026, 11, 25, 13, 30, tzinfo=NY)))

    def test_last_close_skips_holidays_and_knows_half_days(self):
        at = lambda *a: pd.Timestamp(dt.datetime(*a)).tz_localize(NY)
        self.assertEqual(X.last_close_time(at(2026, 11, 27, 15, 0)), at(2026, 11, 27, 13, 0))
        self.assertEqual(X.last_close_time(at(2026, 11, 26, 20, 0)), at(2026, 11, 25, 16, 0))   # Thanksgiving
        self.assertEqual(X.last_close_time(at(2026, 11, 30, 8, 0)), at(2026, 11, 27, 13, 0))    # Monday morning


class NewYorkDate(unittest.TestCase):
    def test_today_is_new_yorks(self):
        late = pd.Timestamp("2026-11-07 03:00", tz="UTC")       # Nov 7 in London, still Nov 6 in New York
        with mock.patch.object(X.pd.Timestamp, "now", lambda tz=None: late.tz_convert(tz)):
            self.assertEqual(X.ny_today(), dt.date(2026, 11, 6))

class HealthBehind(Fresh):
    """Before today's close comes in, the history row is not ok, but it isn't called stale unless it really is."""
    def report(self, fetched_ago):
        S, now = server.S, server.time.time()
        saved = (S.last_tick, S.last_poll)
        S.last_tick, S.history_fetched, S.dates = now, now - fetched_ago, ["2000-01-03"]
        try:
            with mock.patch.object(server, "market_open", lambda *a: False), \
                 mock.patch.object(X, "session_hours", lambda d: (dt.time(0, 0), dt.time(0, 0))):
                if dt.datetime.now(NY).time() < dt.time(0, 31):
                    self.skipTest("too close to midnight in New York")
                r = server.health_report()
        finally:
            S.last_tick, S.last_poll = saved
        return next(x for x in r["rows"] if x["name"] == "Daily price history"), r["problems"]

    def test_behind_is_one_problem(self):
        row, problems = self.report(3600)
        self.assertFalse(row["ok"])
        self.assertTrue(any("closing prices haven't come in" in p for p in problems))
        self.assertFalse(any("over a day" in p for p in problems))

    def test_stale_is_still_reported(self):
        row, problems = self.report(31 * 3600)
        self.assertFalse(row["ok"])
        self.assertTrue(any("over a day" in p for p in problems))


class ImportOddRows(Fresh):
    def post(self, path, body):
        import io
        import json
        h = server.Handler.__new__(server.Handler)
        raw = json.dumps(body).encode()
        h.path, h.headers, h.rfile = path, {"Content-Type": "application/json", "Content-Length": str(len(raw))}, io.BytesIO(raw)
        sent = []
        h.send = lambda code, b, ctype: sent.append((code, json.loads(b)))
        with mock.patch.object(server.agent, "may_ask", lambda handler: True):
            h.do_POST()
        return sent[0]

    def test_rows_that_are_not_objects_are_skipped(self):
        code, out = self.post("/api/me/positions/import", {"rows": [None, "AAPL", 5, {"t": "AAPL", "shares": 2, "cost": 250}]})
        self.assertEqual(code, 200)
        self.assertEqual((out["imported"], out["skipped"]), (1, ["?", "?", "?"]))


class OptionChains(unittest.TestCase):
    def test_each_expiry_is_downloaded_once(self):
        exps = ["2026-11-20", "2026-11-27", "2026-12-04"]
        df = pd.DataFrame({"strike": [100.0], "bid": [1.0], "ask": [1.2], "lastPrice": [1.1], "volume": [10], "openInterest": [20],
                           "impliedVolatility": [0.3]})
        t = mock.MagicMock(options=exps, fast_info={"last_price": 100.0})
        t.option_chain.side_effect = lambda e: mock.Mock(calls=df, puts=df)
        with mock.patch.object(X.yf, "Ticker", lambda sym: t), mock.patch.object(X, "ny_today", lambda: dt.date(2026, 11, 10)):
            out = X.options("ABC", earnings_date="2026-11-21")
        self.assertIsNotNone(out["near"])
        self.assertIsNotNone(out["chain"])
        self.assertEqual(sorted(c.args[0] for c in t.option_chain.call_args_list), exps)

    def test_a_failed_download_is_tried_again(self):
        t = mock.MagicMock(options=["2026-11-20"], fast_info={"last_price": 100.0})
        t.option_chain.side_effect = RuntimeError("Yahoo said no")
        with mock.patch.object(X.yf, "Ticker", lambda sym: t), mock.patch.object(X, "ny_today", lambda: dt.date(2026, 11, 10)):
            out = X.options("ABC")
        self.assertIsNone(out["near"])
        self.assertIsNone(out["chain"])
        self.assertEqual(t.option_chain.call_count, 3)


class WorkbenchRemove(unittest.TestCase):
    def test_removes_the_folder_and_never_raises(self):
        import workbench
        d = workbench.SPACES / "chat-test-remove"
        (d / ".openticker").mkdir(parents=True, exist_ok=True)
        (d / ".openticker" / "you.json").write_text("{}")
        workbench.remove("chat-test-remove")
        self.assertFalse(d.exists())
        workbench.remove("chat-test-remove")     # already gone
        workbench.remove("")                     # not a key
        workbench.remove("../..")
        self.assertTrue(workbench.SPACES.parent.exists())


if __name__ == "__main__":
    unittest.main()
