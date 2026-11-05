"""Tick's answers as durable runs.

An answer is a log. Every step the agent takes is appended as it happens: kept in memory while the answer runs,
and saved to SQLite twice a second. A page is only a reader of that log, so closing or reloading it never stops
the agent, and any page (or the phone) can reattach and replay what it missed.

The agent's own session ID is the save point. Claude Code is started with a session ID we choose, Codex reports
its thread ID; both are kept with the run. If OpenTicker restarts mid-answer, the answer is resumed through the
agent's built-in resume and keeps appending to the same log. Agents that can't resume (OpenCode, Ollama), or a
resume that fails, start the question again.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import uuid

import agent
import personal
import workbench

RESUMABLE = {"claude", "codex"}
RESUME_ASK = ("OpenTicker restarted while you were answering, so your reply was cut off. "
              "Write your complete final answer to my last question now, using what you already looked up.")

_live: dict = {}            # run id -> Live, for answers running in this process
_glock = threading.Lock()


class Live:
    """One running answer: its events, the readers waiting on them, and the agent run behind it."""

    def __init__(self, row, events=None):
        self.row = row
        self.events = list(events or [])        # [(seq, kind, payload)]
        self.saved = len(self.events)           # events[:saved] are already in SQLite
        self.cond = threading.Condition()
        self.done = False
        self.run = None
        self.stopped = False
        self.ws = None                          # the conversation's workbench folder, when the agent has one

    @property
    def rid(self):
        return self.row["id"]

    def append(self, kind, payload):
        if kind == "session":                   # the save point: kept with the run, not shown
            self.row["session"] = payload.get("id")
            personal.run_set(self.rid, session=self.row["session"])
            return
        with self.cond:
            seq = (self.events[-1][0] + 1) if self.events else 1
            self.events.append((seq, kind, payload))
            self.cond.notify_all()

    def flush(self):
        with self.cond:
            todo = self.events[self.saved:]
            self.saved = len(self.events)
        if todo:
            personal.run_events_add(self.rid, todo)


def _flusher():
    while True:
        time.sleep(0.5)
        with _glock:
            lives = list(_live.values())
        for lv in lives:
            try:
                lv.flush()
            except Exception as e:
                agent.srv.log(f"run log save failed: {e!r}")


def summary(events, label):
    """What the conversation keeps of an answer: the text the person saw, the work log, which model, any error.
    Same rules the page uses: statuses before "Asking ..." are setup. What the agent wrote before a tool call is a
    note in the work log ({"n": text}); each tool call is a step ({"t", "k", "d"}); the text after the last is the answer."""
    acc = {"text": "", "steps": [], "tool": False, "thk": False, "by": None, "error": None, "on": False}
    for _, kind, p in events:
        if kind == "status" and not acc["on"]:
            acc["on"] = str(p.get("text", "")).startswith("Asking ")
            continue
        if kind == "reset":
            acc["text"], acc["tool"], acc["error"] = "", False, None
        elif kind == "text":
            acc["text"] += p.get("text", "")
            acc["tool"] = acc["thk"] = False
        elif kind in ("status", "think"):
            if acc["text"].strip():          # what it wrote before this step becomes a note in the log
                acc["steps"].append({"n": acc["text"].strip()[:1500]})
                acc["text"] = ""
            if kind == "think":              # a summary of its thinking: one note per thinking block
                if p.get("new") or not acc["thk"] or not acc["steps"] or not acc["steps"][-1].get("th"):
                    acc["steps"].append({"n": "", "th": 1})
                acc["steps"][-1]["n"] = (acc["steps"][-1]["n"] + p.get("text", ""))[:1500]
                acc["thk"] = True
                continue
            acc["thk"] = False
            step = {"t": p.get("text", "")}
            for k, f in (("kind", "k"), ("id", "id")):
                if p.get(k):
                    step[f] = p[k]
            if p.get("detail"):
                step["d"] = str(p["detail"])[:3000]
            acc["steps"].append(step)
        elif kind == "fail":                 # a step that failed keeps the end of its output, to show why
            for st in reversed(acc["steps"]):
                if p.get("id") and st.get("id") == p["id"]:
                    st["x"] = str(p.get("text", ""))[-1200:]
                    break
        elif kind == "turn" and acc["tool"]:
            acc["text"], acc["tool"] = "", False
        elif kind == "meta" and p.get("model"):
            acc["by"] = p["model"]
        elif kind == "error":
            acc["error"] = p.get("message")
    acc["steps"] = [s for s in acc["steps"] if not (s.get("th") and not s["n"].strip())]
    acc["by"] = label + (f" · {acc['by']}" if acc["by"] else "")
    return acc


def _label(prov):
    return next((p["label"] for p in agent.PROVIDERS if p["id"] == prov), prov)


def start(uid, cid, prov, spec, context):
    """Start an answer in the background and return its id. spec: model, effort, question parts;
    context(): the data to put in the prompt (gathered on the run's own thread)."""
    rid = secrets.token_hex(8)
    row = {"id": rid, "user_id": uid, "chat_id": cid, "provider": prov, "session": None, "status": "running",
           "started": time.time(), "resumes": 0, "spec": spec}
    personal.run_new(row)
    lv = Live(row)
    with _glock:
        _live[rid] = lv
    threading.Thread(target=_work, args=(lv, context), daemon=True).start()
    return rid


def _work(lv, context=None, resume=False):
    row, spec, prov = lv.row, lv.row["spec"], lv.row["provider"]
    label = _label(prov)
    bench = prov in workbench.PROVIDERS and (prov != "claude" or workbench.claude_ready())
    try:
        if bench:
            workbench.build()                       # a toolbox install that failed earlier gets another go
            lv.ws = workbench.space(row.get("chat_id") or row["id"], row["user_id"])
        if not resume:
            lv.append("status", {"text": "Gathering the data"})
            try:
                ctx = context()
            except Exception as e:
                agent.srv.log(f"ask context failed: {e!r}")
                ctx = "(Live data wasn't available just now.)"
            spec["ctx"] = ctx
            spec["prompt"] = agent.build_prompt(spec["q"], ctx, agent.skill(spec["skill"]) if spec.get("skill") else None,
                                                spec.get("history") or [], tools=prov != "ollama", bench=bench)
            personal.run_set(row["id"], spec=json.dumps(spec))
            lv.append("status", {"text": f"Asking {label}"})
        session = None
        if prov == "claude" and not resume:
            session = str(uuid.uuid4())             # choose the save point up front, so even an early crash can resume
            lv.append("session", {"id": session})
        resume_from = row.get("session") if resume and prov in RESUMABLE else None
        got = {"text": False, "error": ""}

        def emit(kind, payload):
            if kind == "text" and payload.get("text"):
                got["text"] = True
            elif kind == "error":
                got["error"] = str(payload.get("message") or "")
            elif kind == "meta" and payload.get("model"):
                try:
                    agent.remember_model(prov, spec.get("model"), payload["model"])
                except Exception:
                    pass
            lv.append(kind, payload)

        def go(resume_id, ws=lv.ws):
            run = agent.Run(prov, RESUME_ASK if resume_id else spec["prompt"], emit, spec.get("model"), spec.get("effort"),
                            session=session, resume=resume_id, workspace=str(ws) if ws else None)
            lv.run = run
            if lv.stopped:
                run.cancelled = True
                return
            run.run()

        if resume:
            lv.append("reset", {})
            lv.append("status", {"text": "Picking up where I left off"})
        t_go = time.time()
        go(resume_from)
        # an error within 30 s may be an older Claude Code rejecting the sandbox settings; but not when the error says what
        # it is (signed out, at its plan limit, not installed), which answering without the workbench wouldn't fix
        quick_fail = got["error"] and time.time() - t_go < 30 and not agent.plain_failure(got["error"])
        if lv.ws and prov == "claude" and not got["text"] and not lv.stopped and (workbench.sandbox_failed(got["error"]) or quick_fail):
            # Claude Code couldn't start its sandbox on this Mac: answer without the workbench, and don't try it again
            why = " ".join(x.strip() for x in (getattr(lv.run, "_err", None) or [])[-4:]) or got["error"]
            agent.srv.log(f"Claude Code's sandbox didn't start, so Tick answers without the workbench for an hour: {why[:400]}")
            workbench.claude_failed()
            lv.ws, session = None, (str(uuid.uuid4()) if prov == "claude" else None)
            if session:
                lv.append("session", {"id": session})
            spec["prompt"] = agent.build_prompt(spec["q"], spec.get("ctx") or "", agent.skill(spec["skill"]) if spec.get("skill") else None,
                                                spec.get("history") or [], tools=True)
            lv.append("reset", {})
            lv.append("status", {"text": "Answering without the workbench"})
            go(None, None)
        if resume and resume_from and not got["text"] and not lv.stopped:
            # the agent couldn't continue its session (it never saved one, or it expired): ask again from the top
            lv.append("reset", {})
            lv.append("status", {"text": "Starting the answer again"})
            go(None)
    except Exception as e:
        lv.append("error", {"message": f"Something went wrong: {e}"})
    _finish(lv, label)


def _finish(lv, label):
    row = lv.row
    with lv.cond:
        events = list(lv.events)
    acc = summary(events, label)
    secs = round(time.time() - row["started"])
    stopped = lv.stopped
    error = acc["error"] or ("Stopped." if stopped and not acc["text"] else None)
    if not acc["text"] and not error:
        error = "No answer came back. Try again, or pick another agent."
    files = workbench.outputs(lv.ws, row["started"]) if lv.ws else []
    lv.append("end", {"secs": secs, "by": acc["by"], "error": error if not acc["text"] else acc["error"], "files": files})
    lv.flush()
    if row.get("chat_id"):
        try:
            personal.chat_add(row["user_id"], row["chat_id"], {"role": "assistant", "text": acc["text"], "steps": acc["steps"][:160],
                                                               "by": acc["by"], "secs": secs, "error": error, "files": files, "ts": time.time()})
        except Exception as e:
            agent.srv.log(f"saving the answer failed: {e!r}")
    personal.run_set(row["id"], status="stopped" if stopped else "error" if error and not acc["text"] else "done", ended=time.time())
    with lv.cond:
        lv.done = True
        lv.cond.notify_all()
    agent.srv.log(f"ask via {row['provider']} ({row['spec'].get('skill') or 'question'}) took {secs}s"
                  + (" after a restart" if row.get("resumes") else ""))
    threading.Timer(120, lambda: _drop(row["id"])).start()   # late readers still get it from memory for a bit


def _drop(rid):
    with _glock:
        _live.pop(rid, None)


def stop(rid, uid):
    with _glock:
        lv = _live.get(rid)
    if not lv or lv.row["user_id"] != uid or lv.done:
        return False
    lv.stopped = True
    if lv.run:
        lv.run.cancel()
    return True


def running_for_chat(uid, cid):
    with _glock:
        for lv in _live.values():
            if lv.row["chat_id"] == cid and lv.row["user_id"] == uid and not lv.done:
                return {"id": lv.rid, "started": lv.row["started"], "provider": lv.row["provider"], "label": _label(lv.row["provider"])}
    return None


def follow(rid, uid, after, write, alive):
    """Send the answer's events after `after` to one reader, then the new ones as they come, until it ends.
    write(seq, kind, payload) sends one; alive() says whether the reader is still there."""
    with _glock:
        lv = _live.get(rid)
    if lv is None:
        row = personal.run_get(rid)
        if not row or row["user_id"] != uid:
            return False
        events = personal.run_events(rid, 0)
        for seq, kind, p in events:
            if seq > after:
                write(seq, kind, p)
        if row["status"] != "running" and not any(k == "end" for _, k, _ in events):
            # an older log that stops without an end (OpenTicker gave up on it): end it, so the page stops waiting
            write(None, "end", {"error": GAVE_UP})
        return True
    if lv.row["user_id"] != uid:
        return False
    write(0, "run", {"id": rid, "started": lv.row["started"], "provider": lv.row["provider"]})
    while alive():
        with lv.cond:
            todo = [e for e in lv.events if e[0] > after]
            if not todo:
                if lv.done:
                    break
                lv.cond.wait(15)
                todo = [e for e in lv.events if e[0] > after]
                if not todo:
                    write(None, "ping", {})   # keeps the connection open through proxies and tells us if the reader left
                    continue
        for seq, kind, p in todo:
            write(seq, kind, p)
            after = seq
    return True


GAVE_UP = "OpenTicker restarted before this answer finished. Ask again."


def _close_finished(row, events):
    """A run whose log already ends (OpenTicker stopped between finishing the answer and closing the run): close it
    instead of answering again, and save the answer to its conversation if it didn't get there."""
    end = next(p for _, k, p in reversed(events) if k == "end")
    acc = summary(events, _label(row["provider"]))
    if row.get("chat_id"):
        chat = personal.chat(row["user_id"], row["chat_id"]) or {}
        if not any(m.get("role") == "assistant" and (m.get("ts") or 0) >= row["started"] for m in chat.get("messages") or []):
            personal.chat_add(row["user_id"], row["chat_id"], {"role": "assistant", "text": acc["text"], "steps": acc["steps"][:160],
                                                               "by": acc["by"], "secs": end.get("secs"), "error": end.get("error"),
                                                               "files": end.get("files") or [], "ts": time.time()})
    personal.run_set(row["id"], status="error" if end.get("error") and not acc["text"] else "done", ended=time.time())


def recover():
    """At start-up: answers that were still running when OpenTicker stopped get picked up again."""
    threading.Thread(target=_flusher, daemon=True).start()
    for row in personal.runs_open():
        try:
            spec = json.loads(row.get("spec") or "{}")
        except Exception:
            spec = {}
        events = personal.run_events(row["id"], 0)
        if any(k == "end" for _, k, _ in events):
            _close_finished(row, events)
            continue
        if row["resumes"] >= 2 or not spec.get("prompt"):
            # give up, and say so in the log too: a page reading it stops reconnecting and shows why
            personal.run_events_add(row["id"], [((events[-1][0] if events else 0) + 1, "end", {"error": GAVE_UP})])
            personal.run_set(row["id"], status="error", ended=time.time())
            if row.get("chat_id"):
                personal.chat_add(row["user_id"], row["chat_id"], {"role": "assistant", "text": "", "steps": [], "by": _label(row["provider"]),
                                                                   "error": GAVE_UP, "ts": time.time()})
            continue
        row = {**row, "spec": spec, "resumes": row["resumes"] + 1, "started": row["started"]}
        personal.run_set(row["id"], resumes=row["resumes"])
        lv = Live(row, events)
        with _glock:
            _live[row["id"]] = lv
        agent.srv.log(f"picking up an unfinished answer ({row['provider']}{', resuming its session' if row.get('session') and row['provider'] in RESUMABLE else ''})")
        threading.Thread(target=_work, args=(lv, None, True), daemon=True).start()
