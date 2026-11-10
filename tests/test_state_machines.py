"""Checks the state machines a statechart audit found broken: market holidays (no invented trading day, no close note),
the workbench switch (a plain error doesn't turn it off; a sandbox failure is retried after an hour), what Tick is told
before its toolbox is ready, and answers across a restart (a log that's given up on ends; a finished one isn't
answered twice). Yahoo, the clock and the agent are faked."""
import datetime as dt
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("OPENTICKER_HOME", tempfile.mkdtemp(prefix="ot-test-"))
sys.path.insert(0, str(ROOT / "app"))
import pandas as pd  # noqa: E402
import agent  # noqa: E402
import personal  # noqa: E402
import runs  # noqa: E402
import server  # noqa: E402
import workbench  # noqa: E402
import yahoo_extra as X  # noqa: E402

NY = ZoneInfo("America/New_York")
personal.init()
agent.bind(server)
UID = personal.DEFAULT_USER


def fresh(name):
    """A conversation id no earlier run has used (the test database can outlive a run)."""
    return name + os.urandom(4).hex()


class Stop(Exception):
    pass


def clock(when):
    """A stand-in for server's `dt` whose now() is `when`."""
    class D(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz else when
    return mock.patch.object(server, "dt", mock.Mock(datetime=D, time=dt.time, date=dt.date, timedelta=dt.timedelta))


def one_pass():
    """Let a server loop run its body once: the first sleep returns, the second stops it."""
    n = {"n": 0}

    def sleep(_):
        n["n"] += 1
        if n["n"] > 1:
            raise Stop()
    return mock.patch.object(server.time, "sleep", sleep)


class Calendar(unittest.TestCase):
    def test_holidays(self):
        self.assertEqual(sorted(str(d) for d in X.market_holidays(2026)),
                         ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
                          "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"])
        self.assertIn(dt.date(2027, 12, 24), X.market_holidays(2027))     # Christmas on a Saturday
        self.assertIn(dt.date(2027, 3, 26), X.market_holidays(2027))      # Good Friday
        self.assertNotIn(dt.date(2021, 12, 31), X.market_holidays(2022))  # New Year's on a Saturday isn't moved back

    def test_hours(self):
        self.assertIsNone(X.session_hours(dt.date(2026, 11, 26)))
        self.assertEqual(X.session_hours(dt.date(2026, 11, 27)), (dt.time(9, 30), dt.time(13)))
        self.assertEqual(X.session_hours(dt.date(2026, 11, 5)), (dt.time(9, 30), dt.time(16)))
        st = X.clock_status(pd.Timestamp("2026-11-26 11:00", tz=NY))
        self.assertEqual((st["status"], st["open"][:16]), ("closed", "2026-11-27T09:30"))
        self.assertEqual(X.clock_status(pd.Timestamp("2026-11-27 14:00", tz=NY))["status"], "closed")
        self.assertEqual(X.clock_status(pd.Timestamp("2026-11-05 11:00", tz=NY))["status"], "open")
        self.assertFalse(server.market_open(dt.datetime(2026, 11, 26, 11, tzinfo=NY)))
        self.assertTrue(server.market_open(dt.datetime(2026, 11, 27, 13, 3, tzinfo=NY)))
        self.assertFalse(server.market_open(dt.datetime(2026, 11, 27, 13, 6, tzinfo=NY)))


class Holiday(unittest.TestCase):
    def setUp(self):
        S = server.S
        self.saved = (S.dates, S.px, S.history_fetched, S.last_tick, S.last_poll, S.poll_after, S.stream_since)
        S.dates, S.px = ["2026-11-24", "2026-11-25"], {"AAPL": [270.0, 272.5], "SPY": [680.0, 681.0]}
        S.history_fetched, S.last_tick, S.last_poll, S.poll_after, S.stream_since = time.time(), 0, 0, 0, 0

    def tearDown(self):
        S = server.S
        S.dates, S.px, S.history_fetched, S.last_tick, S.last_poll, S.poll_after, S.stream_since = self.saved

    def bars(self, day):
        idx = pd.DatetimeIndex([pd.Timestamp(f"{day} 15:59", tz=NY)])
        return mock.patch.object(server, "download_closes", lambda syms, **kw: pd.DataFrame({"AAPL": [272.5], "SPY": [681.0]}, index=idx))

    def poll(self, when, day):
        with clock(when), one_pass(), self.bars(day), mock.patch.object(server.S, "tickers", lambda: ["AAPL", "SPY"]):
            try:
                server.poll_loop()
            except Stop:
                pass

    def test_no_trading_day_on_thanksgiving(self):
        self.poll(dt.datetime(2026, 11, 26, 11, tzinfo=NY), "2026-11-25")
        self.assertEqual(server.S.dates[-1], "2026-11-25")
        self.assertEqual(server.S.last_poll, 0)         # the header doesn't say "polling"

    def test_unexpected_closure_bars_ignored(self):
        """A weekday the calendar doesn't know is closed: the minute bars are yesterday's, so they aren't used."""
        with mock.patch.object(X, "session_hours", lambda d: (dt.time(9, 30), dt.time(16))):
            self.poll(dt.datetime(2026, 11, 26, 11, tzinfo=NY), "2026-11-25")
        self.assertEqual(server.S.dates[-1], "2026-11-25")
        self.assertGreater(server.S.poll_after, time.time())

    def test_trading_day_poll_still_works(self):
        self.poll(dt.datetime(2026, 11, 24, 11, tzinfo=NY), "2026-11-24")   # pretend the 24th is today
        self.assertEqual(server.S.dates[-1], "2026-11-25")                   # older than what we have: no new row
        server.S.last_poll = 0
        self.poll(dt.datetime(2026, 11, 27, 11, tzinfo=NY), "2026-11-27")
        self.assertEqual(server.S.dates[-1], "2026-11-27")

    def test_no_close_note_on_thanksgiving(self):
        server.S.dates = server.S.dates + ["2026-11-26"]     # even if a row for the day got in somehow
        sent = []
        with clock(dt.datetime(2026, 11, 26, 16, 20, tzinfo=NY)), one_pass(), \
                mock.patch.object(personal, "push", lambda uid, title, body, **kw: sent.append(title)):
            try:
                server.close_note_loop()
            except Stop:
                pass
        self.assertEqual(sent, [])


class FakeRun:
    calls = []
    script = []

    def __init__(self, prov, prompt, emit, model=None, effort=None, session=None, resume=None, workspace=None):
        self.emit, self.cancelled, self._err = emit, False, []
        FakeRun.calls.append(workspace)

    def run(self):
        for kind, p in FakeRun.script:
            self.emit(kind, p)

    def cancel(self):
        self.cancelled = True


def ask(cid, script):
    FakeRun.calls, FakeRun.script = [], script
    personal.chat_add(UID, cid, {"role": "user", "text": "How volatile is NVDA?", "ts": time.time()})
    rid = runs.start(UID, cid, "claude", {"q": "How volatile is NVDA?", "skill": None, "history": []}, lambda: "ctx")
    while not runs._live[rid].done:
        time.sleep(0.02)
    return rid


@mock.patch.object(agent, "Run", FakeRun)
@mock.patch.object(workbench, "build", lambda: None)     # never install the real toolbox in a test
class Workbench(unittest.TestCase):
    def setUp(self):
        agent.bind(server)                                # other tests bind a stand-in
        workbench.state.update(claude_ok=True, claude_off=0.0)

    def test_signed_out_keeps_the_workbench(self):
        ask(fresh("chatwb00001"), [("error", {"message": "claude isn't signed in on this Mac. Open Terminal, run `claude` once and sign in, then try again."})])
        self.assertTrue(workbench.state["claude_ok"])
        self.assertEqual(len(FakeRun.calls), 1)          # not asked a second time without the workbench

    def test_sandbox_failure_is_retried_after_an_hour(self):
        ask(fresh("chatwb00002"), [("error", {"message": "Sandbox is unavailable on this system"})])
        self.assertFalse(workbench.state["claude_ok"])
        self.assertEqual([bool(w) for w in FakeRun.calls], [True, False])
        self.assertFalse(workbench.claude_ready())
        workbench.state["claude_off"] -= workbench.RETRY_AFTER + 1
        self.assertTrue(workbench.claude_ready())

    def test_note_before_the_toolbox_is_ready(self):
        with mock.patch.object(workbench, "python", lambda: None):
            n = workbench.note()
        self.assertNotIn("scipy, matplotlib", n)
        self.assertIn("still being set up", n)
        with mock.patch.object(workbench, "python", lambda: Path("/x/python")):
            self.assertEqual(workbench.note(), workbench.NOTE)


@mock.patch.object(agent, "Run", FakeRun)
class Restart(unittest.TestCase):
    def setUp(self):
        agent.bind(server)
        workbench.state["claude_ok"] = False       # keep it simple: no workbench folders
        runs._live.clear()

    def tearDown(self):
        workbench.state["claude_ok"] = True

    def orphan(self, cid, spec, resumes, events):
        r = {"id": os.urandom(8).hex(), "user_id": UID, "chat_id": cid, "provider": "claude", "session": "s" * 36,
             "status": "running", "started": time.time() - 5, "resumes": resumes, "spec": spec}
        personal.run_new(r)
        personal.run_events_add(r["id"], [(i + 1, k, p) for i, (k, p) in enumerate(events)])
        return r["id"]

    def read(self, rid):
        got = []
        runs.follow(rid, UID, 0, lambda s, k, p: got.append((k, p)), lambda: True)
        return got

    def test_given_up_answer_ends(self):
        for cid, spec, resumes in ((fresh("chatgone001"), {"q": "x", "prompt": "p"}, 2), (fresh("chatgone002"), {"q": "x"}, 0)):
            rid = self.orphan(cid, spec, resumes, [("status", {"text": "Gathering the data"})])
            runs.recover()
            got = self.read(rid)
            self.assertEqual(got[-1], ("end", {"error": runs.GAVE_UP}))
            self.assertEqual(personal.run_get(rid)["status"], "error")

    def test_old_log_without_end_is_ended(self):
        rid = self.orphan(fresh("chatgone003"), {"q": "x"}, 2, [("status", {"text": "Gathering the data"})])
        personal.run_set(rid, status="error")             # given up by an older OpenTicker
        self.assertEqual(self.read(rid)[-1][0], "end")

    def test_finished_answer_not_answered_twice(self):
        cid = fresh("chatdup0001")
        rid = ask(cid, [("text", {"text": "NVDA's 30-day volatility is 48%."})])
        personal.run_set(rid, status="running", ended=None)     # stopped after saving the answer, before closing the run
        runs._live.clear()
        FakeRun.calls = []
        runs.recover()
        self.assertEqual(FakeRun.calls, [])
        self.assertEqual(len([m for m in personal.chat(UID, cid)["messages"] if m["role"] == "assistant"]), 1)
        self.assertEqual(personal.run_get(rid)["status"], "done")

    def test_given_up_answer_told_once_across_a_stop(self):
        """OpenTicker stops in the middle of giving up on an answer, at either of its last two writes: the next start
        still tells the conversation, exactly once (the TickAnswer model's EveryQuestionAnswered and OneAnswer)."""
        for n, (mod, name) in enumerate(((personal, "chat_add"), (personal, "run_set"))):
            cid = fresh(f"chatgone10{n}")
            personal.chat_add(UID, cid, {"role": "user", "text": "q", "ts": time.time() - 10})
            rid = self.orphan(cid, {"q": "q"}, 0, [("status", {"text": "Gathering the data"})])
            real = getattr(mod, name)

            def dies(*a, real=real, **kw):
                if kw.get("status") == "error" or (len(a) > 2 and a[2].get("error") == runs.GAVE_UP):
                    raise Stop()
                return real(*a, **kw)
            with mock.patch.object(mod, name, dies):
                try:
                    runs.recover()
                except Stop:
                    pass
            runs.recover()
            replies = [m for m in personal.chat(UID, cid)["messages"] if m["role"] == "assistant"]
            self.assertEqual([m.get("error") for m in replies], [runs.GAVE_UP], name)
            self.assertEqual(personal.run_get(rid)["status"], "error", name)

    def test_deleting_a_conversation_stops_its_answer(self):
        """Deleted while its answer runs: the answer stops, and finishing doesn't bring the conversation back."""
        import io
        import json
        cid, go = fresh("chatdel0001"), threading.Event()

        class Slow(FakeRun):
            def run(self):
                self.emit("status", {"text": "Asking Claude Code"})
                self.emit("text", {"text": "Half an answer"})
                go.set()
                while not self.cancelled:
                    time.sleep(0.01)

        personal.chat_add(UID, cid, {"role": "user", "text": "q", "ts": time.time()})
        with mock.patch.object(agent, "Run", Slow):
            rid = runs.start(UID, cid, "claude", {"q": "q", "skill": None, "history": []}, lambda: "ctx")
            self.assertTrue(go.wait(5))
            h = server.Handler.__new__(server.Handler)
            raw = json.dumps({"id": cid}).encode()
            h.path, h.headers, h.rfile = "/api/ask/chat/delete", {"Content-Type": "application/json", "Content-Length": str(len(raw))}, io.BytesIO(raw)
            sent = []
            h.send = lambda code, b, ctype: sent.append(code)
            with mock.patch.object(server.agent, "may_ask", lambda handler: True):
                h.do_POST()
            self.assertEqual(sent, [200])
            for _ in range(250):
                if runs._live[rid].done:
                    break
                time.sleep(0.02)
        self.assertTrue(runs._live[rid].done)
        self.assertTrue(runs._live[rid].stopped)
        self.assertIsNone(personal.chat(UID, cid))
        self.assertEqual(personal.run_get(rid)["status"], "stopped")

    def test_ask_again_replaces_the_answer(self):
        """"Ask again" through /api/ask: once the new answer lands, the conversation has one question and one answer."""
        import io
        import json
        cid = fresh("chatretry01")
        ask(cid, [("status", {"text": "Asking Claude Code"}), ("text", {"text": "Old answer."})])
        FakeRun.script = [("status", {"text": "Asking Claude Code"}), ("text", {"text": "New answer."})]
        got = {}
        h = server.Handler.__new__(server.Handler)
        raw = json.dumps({"provider": "claude", "q": "How volatile is NVDA?", "chat": cid, "retry": True, "history": []}).encode()
        h.path, h.headers, h.rfile = "/api/ask", {"Content-Type": "application/json", "Content-Length": str(len(raw))}, io.BytesIO(raw)
        h.send = lambda code, b, ctype: got.setdefault("refused", code)
        with mock.patch.object(server.agent, "may_ask", lambda handler: True), mock.patch.object(agent, "context_for", lambda *a: "ctx"), \
                mock.patch.object(server.Handler, "follow_run", lambda self, rid, uid, after: got.setdefault("rid", rid)):
            h.do_POST()
        self.assertNotIn("refused", got)
        while not runs._live[got["rid"]].done:
            time.sleep(0.02)
        msgs = personal.chat(UID, cid)["messages"]
        self.assertEqual([(m["role"], m["text"]) for m in msgs], [("user", "How volatile is NVDA?"), ("assistant", "New answer.")])
        self.assertEqual(personal.chat_drop_answer(UID, fresh("chatnone01")), [])   # nothing to take from a missing conversation

    def test_first_answer_still_makes_its_conversation(self):
        cid = fresh("chatnew0001")
        ask(cid, [("status", {"text": "Asking Claude Code"}), ("text", {"text": "Done."})])
        self.assertEqual([m["role"] for m in personal.chat(UID, cid)["messages"]], ["user", "assistant"])

    def test_finished_answer_saved_if_missing(self):
        """Stopped after the log ended but before the answer reached the conversation: it's saved, once."""
        cid = fresh("chatdup0002")
        personal.chat_add(UID, cid, {"role": "user", "text": "q", "ts": time.time() - 10})
        self.orphan(cid, {"q": "q", "prompt": "p"}, 0, [("status", {"text": "Asking Claude Code"}), ("text", {"text": "Done."}),
                                                             ("end", {"secs": 3, "by": "Claude Code", "error": None, "files": []})])
        runs.recover()
        answers = [m for m in personal.chat(UID, cid)["messages"] if m["role"] == "assistant"]
        self.assertEqual([m["text"] for m in answers], ["Done."])



class SignalsScan(unittest.TestCase):
    """Two pages asking for momentum scores at once start one scan, not two (the Signals model's OneScanAtATime)."""
    def test_one_scan_at_a_time(self):
        started, gate = [], threading.Event()

        def scan():
            started.append(1)
            gate.wait(5)
            server.SIG["running"] = False
        saved = dict(server.SIG)
        server.SIG.update(rows=[], running=False, failAt=0)
        try:
            with mock.patch.object(server, "signals_scan", scan), \
                    mock.patch.dict(server.S.holdings, {"SPY": {"holdings": [{"t": "AAPL"}]}}):
                ts = [threading.Thread(target=server.signals_payload, args=(True,)) for _ in range(4)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
                self.assertTrue(server.signals_payload(True)["running"])
                for _ in range(50):                    # the scan thread starts on its own
                    if started:
                        break
                    time.sleep(0.02)
                time.sleep(0.2)                        # time for a second one to show up, if there were one
                self.assertEqual(len(started), 1)
                gate.set()
        finally:
            gate.set()
            server.SIG.clear()
            server.SIG.update(saved)

if __name__ == "__main__":
    unittest.main()
