---- MODULE TickAnswer ----
\* One question to Tick, from the run on this Mac (app/runs.py) to the page that reads its log (askDrive in
\* app/static/ask.js), with OpenTicker allowed to stop between any two writes. Each action below is one step in the
\* code; the comment above it names the lines. SKILL.md has the full map.
EXTENDS Naturals

CONSTANT MaxResumes     \* runs.recover gives up once a run has been resumed this often (row["resumes"] >= 2)

VARIABLES
    srv,        \* where the run is; see Phases below
    up,         \* OpenTicker is running
    resumes,    \* runs.resumes in SQLite
    answers,    \* assistant messages for this question in the conversation (personal.chat_add)
    page        \* what the open page shows

vars == <<srv, up, resumes, answers, page>>

\* Phases of srv, and what SQLite holds in each:
\*   "none"       nothing yet
\*   "gathering"  run row "running", no prompt saved yet (spec has no "prompt")
\*   "asking"     prompt saved; the agent is answering, or _finish has not flushed "end" yet
\*   "ended"      "end" is in the saved log; the conversation has no answer yet
\*   "saved"      the answer is in the conversation; the row still says "running"
\*   "givingUp"   recover wrote "end" (GAVE_UP) to the log; the row still says "running"
\*   "closed"     the row is done, stopped or error, and the conversation has its answer
Open == {"gathering", "asking", "ended", "saved", "givingUp"}   \* personal.runs_open() returns it at start-up
LogEnds == {"ended", "saved", "givingUp", "closed"}

Init == srv = "none" /\ up = TRUE /\ resumes = 0 /\ answers = 0 /\ page = "idle"

\* POST /api/ask -> runs.start: run_new(row) with status "running", then _work on its own thread
YouAsk == page = "idle" /\ srv = "none" /\ up
    /\ srv' = "gathering" /\ page' = "reading"
    /\ UNCHANGED <<up, resumes, answers>>

\* _work: context(), build_prompt, then personal.run_set(spec=...) saves the prompt
PromptSaved == srv = "gathering" /\ up
    /\ srv' = "asking"
    /\ UNCHANGED <<up, resumes, answers, page>>

\* _finish: lv.append("end", ...) then lv.flush()
EndSaved == srv = "asking" /\ up
    /\ srv' = "ended"
    /\ UNCHANGED <<up, resumes, answers, page>>

\* _finish: personal.chat_add(...)
AnswerSaved == srv = "ended" /\ up
    /\ srv' = "saved" /\ answers' = answers + 1
    /\ UNCHANGED <<up, resumes, page>>

\* _finish: personal.run_set(status=...), the same whether the agent finished or you pressed Stop (runs.stop); also the second half of _close_finished
RunClosed == srv = "saved" /\ up
    /\ srv' = "closed"
    /\ UNCHANGED <<up, resumes, answers, page>>

\* The process stops (quit, update, crash, Mac asleep) between any two writes.
\* The page's stream drops with it.
OpenTickerStops == up /\ srv # "none"
    /\ up' = FALSE
    /\ page' = (IF page = "reading" THEN "reconnecting" ELSE page)
    /\ UNCHANGED <<srv, resumes, answers>>

\* ---- runs.recover() at start-up, for each row in personal.runs_open()

\* a log that already has "end": _close_finished adds the answer only if the conversation lacks one, then closes
ComesBackCloses == ~up /\ srv \in {"ended", "saved", "givingUp"}
    /\ up' = TRUE /\ srv' = "saved"
    /\ answers' = (IF answers = 0 THEN 1 ELSE answers)
    /\ UNCHANGED <<resumes, page>>

\* no prompt saved, or resumed too often: append "end" with GAVE_UP to the log
ComesBackGivesUp == ~up /\ (srv = "gathering" \/ (srv = "asking" /\ resumes >= MaxResumes))
    /\ up' = TRUE /\ srv' = "givingUp"
    /\ UNCHANGED <<resumes, answers, page>>

\* ... then personal.chat_add(GAVE_UP): the log ends and the conversation has its reply, as in "saved"
GiveUpTold == srv = "givingUp" /\ up
    /\ srv' = "saved" /\ answers' = answers + 1
    /\ UNCHANGED <<up, resumes, page>>
\* ... then personal.run_set(status="error"), which is RunClosed

\* resume: run_set(resumes=+1) and _work(resume=True), which appends to the same log
ComesBackResumes == ~up /\ srv = "asking" /\ resumes < MaxResumes
    /\ up' = TRUE /\ resumes' = resumes + 1
    /\ UNCHANGED <<srv, answers, page>>

\* a closed run is not in runs_open(): start-up leaves it alone
ComesBackIdle == ~up /\ srv = "closed"
    /\ up' = TRUE
    /\ UNCHANGED <<srv, resumes, answers, page>>

\* ---- the page (askDrive)

\* the page fetches /api/ask/run?after=0 again and replays the whole log
Reattach == page = "reconnecting" /\ up
    /\ page' = "reading"
    /\ UNCHANGED <<srv, up, resumes, answers>>

\* the "end" event arrives: runs.follow sends it from memory or from SQLite
ShowEnd == page = "reading" /\ up /\ srv \in LogEnds
    /\ page' = "shown"
    /\ UNCHANGED <<srv, up, resumes, answers>>

\* after 45 tries (about 100 seconds): "Lost touch with OpenTicker. Open this conversation again in a minute ..."
PageGivesUp == page = "reconnecting" /\ ~up
    /\ page' = "lost"
    /\ UNCHANGED <<srv, up, resumes, answers>>

Finished == up /\ srv = "closed" /\ page \in {"shown", "lost"} /\ UNCHANGED vars

Next == YouAsk \/ PromptSaved \/ EndSaved \/ AnswerSaved \/ RunClosed \/ OpenTickerStops
    \/ ComesBackCloses \/ ComesBackGivesUp \/ GiveUpTold \/ ComesBackResumes \/ ComesBackIdle
    \/ Reattach \/ ShowEnd \/ PageGivesUp \/ Finished

Spec == Init /\ [][Next]_vars

\* ---- Rules

\* A question never gets two answers in its conversation, whenever OpenTicker stops.
OneAnswer == answers <= 1

\* Every question gets a reply in its conversation (an answer or why there isn't one), whenever OpenTicker stops.
EveryQuestionAnswered == srv = "closed" => answers = 1

\* The page ends a question only once the log says it ended.
PageEndsWithTheLog == page = "shown" => srv \in LogEnds

====
