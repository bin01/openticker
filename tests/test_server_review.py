"""The review of 2026-11-10: the next trading day knows holidays, alert ids are never reused, one Yahoo fetch per cold
key, the base version moves only when it must, static files revalidate and gzip, and the pairing key can be reset.
Nothing here touches the network."""
import gzip
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import personal  # noqa: E402
import server  # noqa: E402
import yahoo_extra as X  # noqa: E402


class NextTradingDay(unittest.TestCase):
    def test_skips_weekends_and_holidays(self):
        self.assertEqual(personal._next_day("2026-11-25", X.market_holidays), "2026-11-27")   # Thanksgiving
        self.assertEqual(personal._next_day("2026-12-24", X.market_holidays), "2026-12-28")   # Christmas, then the weekend
        self.assertEqual(personal._next_day("2026-11-06"), "2026-11-09")                      # weekends only by default


class Db(unittest.TestCase):
    def setUp(self):
        self.old = personal._conn
        personal._conn = sqlite3.connect(":memory:", check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()

    def tearDown(self):
        personal._conn.close()
        personal._conn = self.old


class EarningsTomorrow(Db):
    def test_reports_after_a_holiday_count_as_tomorrow(self):
        personal.set_watch("me", "ABC", True)
        with mock.patch.object(personal, "push", lambda *a, **k: True):
            fired = personal.evaluate("me", {"ABC": [10.0, 10.0]}, ["2026-11-24", "2026-11-25"], {}, {"ABC": {"date": "2026-11-27"}},
                                      holidays=X.market_holidays)
        self.assertEqual([f[1] for f in fired], ["ABC reports tomorrow"])


OLD_ALERTS = """create table users(id text primary key, name text, created real);
insert into users values('me', 'Me', 1);
create table alerts(id integer primary key, user_id text, kind text, t text,
    scope text, value real, active integer default 1, created real);
create table events(id integer primary key, user_id text, ts real, t text, kind text,
    title text, body text, dedup text, read integer default 0, unique(user_id, dedup));"""


class AlertIds(unittest.TestCase):
    def open(self, path):
        personal._conn = sqlite3.connect(path, check_same_thread=False)
        personal._conn.row_factory = sqlite3.Row
        personal.init()

    def test_old_database_is_upgraded_and_ids_never_come_back(self):
        old = personal._conn
        try:
            with tempfile.TemporaryDirectory() as d:
                path = str(Path(d, "app.db"))
                c = sqlite3.connect(path)
                c.executescript(OLD_ALERTS)
                c.executemany("insert into alerts(id, user_id, kind, scope, value, created) values(?,?,?,?,?,?)",
                              [(1, "me", "move", "both", 5.0, 1.0), (2, "me", "above", None, 300.0, 1.0)])
                c.execute("insert into events(user_id, ts, t, kind, title, body, dedup) values('me', 1, 'AAPL', 'above', 'x', 'y', '7|AAPL|2026-11-06')")
                c.execute("insert into events(user_id, ts, kind, title, body, dedup) values('me', 1, 'close', 'x', 'y', 'close|2026-11-06')")
                c.commit()
                c.close()
                self.open(path)
                self.assertEqual([(a["id"], a["kind"], a["value"]) for a in personal.alerts("me")], [(1, "move", 5.0), (2, "above", 300.0)])
                self.assertEqual(personal.add_alert("me", "high52", scope="both"), 8)   # above the 7 in an old dedup key
                personal.delete_alert("me", 8)
                personal._conn.close()
                self.open(path)                                                       # a second start changes nothing
                self.assertEqual(personal.add_alert("me", "low52", scope="both"), 9)
                sql = personal._conn.execute("select sql from sqlite_master where name='alerts'").fetchone()[0]
                self.assertIn("autoincrement", sql.lower())
                personal._conn.close()
        finally:
            personal._conn = old


class SingleFlight(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(server, "_detail_cache", {}), mock.patch.object(server, "_disk_cache", {}),
                  mock.patch.object(server, "_stale_keys", set()), mock.patch.object(server, "_yf_fresh", lambda: None),
                  mock.patch.object(server.time, "sleep", lambda s: None)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def crowd(self, fn, n=6):
        out = []

        def ask():
            try:
                out.append(server.cached(("info", "ZZZ"), 60, fn))
            except Exception as e:
                out.append(e)
        ts = [threading.Thread(target=ask) for _ in range(n)]
        for t in ts:
            t.start()
        return out, ts

    def test_one_fetch_for_many_callers(self):
        calls, gate = [], threading.Event()

        def fn():
            calls.append(1)
            gate.wait(5)
            return {"a": 1}
        out, ts = self.crowd(fn)
        time.sleep(0.2)
        gate.set()
        for t in ts:
            t.join(5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(out, [{"a": 1}] * 6)

    def test_a_failure_releases_the_waiters(self):
        calls, gate = [], threading.Event()

        def fn():
            calls.append(1)
            gate.wait(5)
            raise RuntimeError("500 Server Error")
        out, ts = self.crowd(fn)
        time.sleep(0.2)
        gate.set()
        for t in ts:
            t.join(5)
        self.assertFalse(any(t.is_alive() for t in ts))
        self.assertEqual(len(calls), 2)                           # the first caller's one retry, nobody else's
        self.assertTrue(all(isinstance(e, RuntimeError) for e in out) and len(out) == 6)
        self.assertEqual(server._inflight, {})


class Http(Db):
    def setUp(self):
        super().setUp()
        S = server.S
        self.saved = (S.dates, S.px, S.version)
        S.dates, S.px = ["2026-11-05", "2026-11-06"], {t: [100.0 + i, 101.0 + i] for i, t in enumerate(["SPY", "AAPL", "MSFT"])}
        S.px.update({f"T{i}": [float(i), float(i + 1)] for i in range(200)})   # enough to be worth gzipping
        self.old_srv, server.agent.srv = server.agent.srv, server
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.S.dates, server.S.px, server.S.version = self.saved
        server.agent.srv = self.old_srv
        super().tearDown()

    def get(self, path, **headers):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers), timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def post(self, path, body=None):
        req = urllib.request.Request(self.base + path, json.dumps(body or {}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_static_revalidates_and_gzips(self):
        code, h, body = self.get("/static/ux.js")
        self.assertEqual((code, h["Cache-Control"]), (200, "no-cache"))
        self.assertEqual(int(h["Content-Length"]), len(body))
        self.assertEqual(self.get("/static/ux.js", **{"If-None-Match": h["ETag"]})[0], 304)
        code, hz, z = self.get("/static/ux.js", **{"Accept-Encoding": "gzip"})
        self.assertEqual((hz["Content-Encoding"], int(hz["Content-Length"])), ("gzip", len(z)))
        self.assertEqual(gzip.decompress(z), body)
        self.assertEqual(self.get("/static/ux.js", **{"Accept-Encoding": "gzip", "If-None-Match": hz["ETag"]})[0], 304)
        self.assertNotIn("Content-Encoding", self.get("/static/ux.js", **{"Accept-Encoding": "gzip;q=0"})[1])
        self.assertEqual(self.get("/", **{"If-None-Match": self.get("/")[1]["ETag"]})[0], 304)

    def test_an_edited_file_gets_a_new_etag(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(server, "STATIC", Path(d)):
            f = Path(d, "x.js")
            f.write_text("let a=1;")
            tag = self.get("/static/x.js")[1]["ETag"]
            f.write_text("let a=2;")
            code, h, body = self.get("/static/x.js", **{"If-None-Match": tag})
            self.assertEqual((code, body), (200, b"let a=2;"))
            self.assertNotEqual(h["ETag"], tag)

    def test_base_is_gzipped(self):
        code, h, plain = self.get("/api/base")
        code, hz, z = self.get("/api/base", **{"Accept-Encoding": "gzip, deflate"})
        self.assertEqual((code, hz["Content-Encoding"], hz["Cache-Control"]), (200, "gzip", "no-store"))
        self.assertEqual(json.loads(gzip.decompress(z)), json.loads(plain))
        self.assertLess(len(z), len(plain))

    def test_version_moves_only_for_tickers_and_positions(self):
        v = server.S.version
        self.post("/api/me/read")
        self.post("/api/me/alert/toggle", {"id": 1, "on": False})
        self.assertEqual(server.S.version, v)
        self.post("/api/me/watch", {"t": "AAPL", "on": True})
        self.assertEqual(server.S.version, v + 1)
        self.post("/api/me/watch", {"t": "AAPL", "on": True})   # already there
        self.assertEqual(server.S.version, v + 1)
        self.post("/api/me/positions/save", {"lots": [{"t": "AAPL", "shares": 2, "cost": 100}]})
        self.assertEqual(server.S.version, v + 2)

    def test_pairing_key_reset(self):
        old = server.agent.pair_token()
        out = self.post("/api/app/pair/reset")
        new = server.agent.pair_token()
        self.assertNotEqual(new, old)
        self.assertTrue(out["pair"].endswith("#pair=" + new))
        phone = mock.Mock(client_address=("192.168.1.20", 5000), headers={"Host": "127.0.0.1:1", "X-Ask-Token": old})
        self.assertFalse(server.agent.may_ask(phone))
        phone.headers["X-Ask-Token"] = new
        self.assertTrue(server.agent.may_ask(phone))
        with mock.patch.object(server.agent, "is_local", lambda h: False):   # a paired phone can't reset it
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.post("/api/app/pair/reset")
            self.assertEqual(e.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
