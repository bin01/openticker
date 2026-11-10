---- MODULE Signals ----
\* Screener, Momentum signals: the server's scan (signals_payload and signals_scan in app/server.py, guarded by
\* _sig_lock) and the page's copy of it (SIG, sigWait, loadSignals and renderSignals in app/static/pages.js).
\* Two pages can ask at once (the Mac and a phone), and each request runs on its own server thread. SKILL.md has the map.
EXTENDS Naturals

VARIABLES
    onPage,     \* the page shows Screener -> Momentum signals (page === "screener" && scrSel === "signals")
    view,       \* the page's SIG: "none" (null), "progress" (SIG.running), "scores", "error"
    polling,    \* sigWait: a timer that will call loadSignals again
    scans,      \* signals_scan threads running
    running,    \* the server's SIG["running"]
    srvFresh,   \* the server's scores are from the latest close (not stale in signals_payload)
    pageFresh,  \* the scores on the page are from the latest close
    asking      \* request threads in signals_payload that saw stale scores and have not reached _sig_lock yet

vars == <<onPage, view, polling, scans, running, srvFresh, pageFresh, asking>>

Init == onPage = FALSE /\ view = "none" /\ polling = FALSE /\ scans = 0 /\ running = FALSE
    /\ srvFresh = FALSE /\ pageFresh = FALSE /\ asking = 0

\* another device (the phone) asks: signals_payload works out `stale` outside the lock
Ask == asking < 2 /\ ~srvFresh /\ asking' = asking + 1
    /\ UNCHANGED <<onPage, view, polling, scans, running, srvFresh, pageFresh>>

\* inside _sig_lock: start a scan only if none is running (SIG["running"] = True, then the thread)
TakeLock == asking > 0 /\ asking' = asking - 1
    /\ (IF ~running THEN running' = TRUE /\ scans' = scans + 1 ELSE UNCHANGED <<running, scans>>)
    /\ UNCHANGED <<onPage, view, polling, srvFresh, pageFresh>>

\* the page's own request (loadSignals -> signals_payload): stale scores with no scan running start one under
\* _sig_lock, unless the last scan failed under five minutes ago (failAt), which answers with its error. The page sets
\* SIG from the answer, and sigWait (3 s) if SIG.running.
Answer == \/ /\ (running \/ srvFresh)
             /\ view' = IF running THEN "progress" ELSE "scores"
             /\ pageFresh' = (srvFresh /\ ~running) /\ polling' = running
             /\ UNCHANGED <<scans, running>>
          \/ /\ ~running /\ ~srvFresh
             /\ running' = TRUE /\ scans' = scans + 1
             /\ view' = "progress" /\ polling' = TRUE /\ pageFresh' = FALSE
          \/ /\ ~running /\ ~srvFresh
             /\ view' = "error" /\ polling' = FALSE /\ pageFresh' = FALSE
             /\ UNCHANGED <<scans, running>>

\* you click Momentum signals: renderSignals calls loadSignals only when SIG is null
YouOpenScreener == ~onPage /\ onPage' = TRUE
    /\ (IF view = "none" THEN Answer ELSE UNCHANGED <<view, polling, pageFresh, scans, running>>)
    /\ UNCHANGED <<srvFresh, asking>>
YouLeave == onPage /\ onPage' = FALSE /\ UNCHANGED <<view, polling, scans, running, srvFresh, pageFresh, asking>>

\* the sigWait timer fires: it reloads only if you are still on the screener's signals
PollFires == polling
    /\ IF onPage THEN Answer /\ UNCHANGED <<onPage, srvFresh, asking>>
       ELSE polling' = FALSE /\ UNCHANGED <<onPage, view, scans, running, srvFresh, pageFresh, asking>>

\* "Try again" on an error: SIG = null, then loadSignals
YouRetry == onPage /\ view = "error" /\ Answer /\ UNCHANGED <<onPage, srvFresh, asking>>

\* a scan thread ends: SIG.update(rows=..., running=False), or the except branch (error, failAt), then finally running=False
ScanEnds == scans > 0 /\ scans' = scans - 1 /\ running' = FALSE
    /\ srvFresh' \in {TRUE, srvFresh}
    /\ UNCHANGED <<onPage, view, polling, pageFresh, asking>>

\* a new close comes out (or six hours pass): the server's scores go stale
NewClose == srvFresh /\ ~running /\ srvFresh' = FALSE /\ pageFresh' = FALSE
    /\ UNCHANGED <<onPage, view, polling, scans, running, asking>>

Next == Ask \/ TakeLock \/ YouOpenScreener \/ YouLeave \/ PollFires \/ YouRetry \/ ScanEnds \/ NewClose
Spec == Init /\ [][Next]_vars

\* keeps the model finite even if a change lets scans pile up (OneScanAtATime still sees the second one)
Bound == scans <= 2

\* ---- Rules

\* Only one scan runs at a time (each one downloads a year of prices for about 600 stocks).
OneScanAtATime == scans <= 1

\* A progress bar on screen keeps moving: the page is still checking.
ProgressMoves == onPage /\ view = "progress" => polling

\* After a new close, the open screener gets the new scores.
GetsNewClose == onPage /\ view = "scores" /\ ~pageFresh => polling
====
