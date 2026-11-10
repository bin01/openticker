---- MODULE LinkAccount ----
\* One linked brokerage, as Settings, Accounts shows it: app/links.py on the server, app/static/links.js on the page.
\* status is the links row in SQLite and survives a restart; pending (links.PENDING), preview (links.PREVIEW) and
\* worker (a _fetch_async or _sync_async thread) live only in the server's memory. SKILL.md has the full map.
VARIABLES status, synced, pending, preview, worker
vars == <<status, synced, pending, preview, worker>>

\* status: "none" (no row), "signin", "fetching", "review", "ok", "auth", "error"
\* synced: links.synced is set (the link mirrored positions at least once)

Init == status = "none" /\ synced = FALSE /\ pending = FALSE /\ preview = FALSE /\ worker = FALSE

\* _refresh_async: a link that synced before syncs straight away (_sync_async); a new one is read for review (_fetch_async)
StartRead == status' = "fetching" /\ worker' = TRUE

\* ---- you, in Settings: only the buttons linksSection() draws for each status

\* a preset's Add button -> connect(): PENDING[state] = ..., add_link(status="signin")
YouConnect == status = "none" /\ status' = "signin" /\ pending' = TRUE /\ synced' = FALSE
    /\ UNCHANGED <<preview, worker>>

\* the browser comes back -> callback(): PENDING.pop(state), exchange, put_secret, _refresh_async
YouAllowInBrowser == status = "signin" /\ pending /\ StartRead /\ pending' = FALSE
    /\ UNCHANGED <<synced, preview>>
\* callback() with ?error=access_denied, or the exchange fails: "auth" for a link that synced before, else "error"
YouDenyInBrowser == status = "signin" /\ pending /\ pending' = FALSE
    /\ status' = (IF synced THEN "auth" ELSE "error")
    /\ UNCHANGED <<synced, preview, worker>>

\* Cancel on a signin/fetching row -> cancel(): a link that never synced is disconnected; one that did drops what
\* it waited for and goes back to "ok" (or "auth" when it was waiting on a sign-in), positions untouched. A read
\* still running finds it changed.
YouCancel == status \in {"signin", "fetching"}
    /\ IF synced
       THEN status' = (IF status = "signin" THEN "auth" ELSE "ok") /\ pending' = FALSE /\ preview' = FALSE
            /\ UNCHANGED <<synced, worker>>
       ELSE status' = "none" /\ pending' = FALSE /\ preview' = FALSE /\ worker' = FALSE /\ UNCHANGED synced

\* Review: the sheet opens the preview, or, if it's gone, retry() reads again and reopens it when ready
YouReviewLost == status = "review" /\ ~preview /\ StartRead /\ UNCHANGED <<synced, pending, preview>>
\* Review -> Add -> apply(): PREVIEW.pop, mirror_link, status "ok", synced set
YouAdd == status = "review" /\ preview /\ status' = "ok" /\ synced' = TRUE /\ preview' = FALSE
    /\ UNCHANGED <<pending, worker>>
\* Review -> Don't add: cancel() on a first-time link (a synced link never reaches review now)
YouDontAdd == status = "review" /\ preview /\ ~synced
    /\ status' = "none" /\ preview' = FALSE /\ UNCHANGED <<synced, pending, worker>>

\* Try again on an error row -> retry() -> _refresh_async
YouRetry == status = "error" /\ StartRead /\ UNCHANGED <<synced, pending, preview>>
\* Sign in again on an auth row -> reconnect(): PENDING[state] = ..., status "signin"
YouSignInAgain == status = "auth" /\ status' = "signin" /\ pending' = TRUE /\ UNCHANGED <<synced, preview, worker>>
\* disconnect(): remove_link. Disconnect -> Keep them / Remove them on an ok row, or on a synced auth or error row;
\* Remove straight away on an error or auth row of a link that never synced.
YouDisconnect == status \in {"ok", "auth", "error"}
    /\ status' = "none" /\ synced' = FALSE /\ preview' = FALSE /\ pending' = FALSE /\ worker' = FALSE

\* ---- the server

\* _fetch_async (never synced): PREVIEW[lid] = got and status "review", or status "auth"/"error"
ReadWorks == worker /\ ~synced /\ worker' = FALSE /\ preview' = TRUE /\ status' = "review" /\ UNCHANGED <<synced, pending>>
ReadFails == worker /\ ~synced /\ worker' = FALSE /\ status' \in {"error", "auth"} /\ UNCHANGED <<synced, pending, preview>>
\* _sync_async (synced before): sync() -> apply() sets "ok"; AuthNeeded sets "auth"; any other failure "ok" with an error
SyncDone == worker /\ synced /\ worker' = FALSE /\ status' \in {"ok", "auth"} /\ UNCHANGED <<synced, pending, preview>>
\* the daily sync (loop -> due -> sync) or Sync now
SyncRuns == status = "ok" /\ status' \in {"ok", "auth"} /\ UNCHANGED <<synced, pending, preview, worker>>
\* OpenTicker quits and starts again: memory is gone. bind() -> _after_restart puts "signin" to "auth" and
\* "fetching"/"review" to "fetching"; links.loop() -> _read_again starts a read for each "fetching" row once prices are loaded.
Restart == (pending \/ preview \/ worker)
    /\ status' = (CASE status = "signin" -> "auth"
                    [] status \in {"fetching", "review"} -> "fetching"
                    [] OTHER -> status)
    /\ pending' = FALSE /\ preview' = FALSE /\ worker' = (status' = "fetching")
    /\ UNCHANGED synced

Next == YouConnect \/ YouAllowInBrowser \/ YouDenyInBrowser \/ YouCancel \/ YouReviewLost \/ YouAdd \/ YouDontAdd
    \/ YouRetry \/ YouSignInAgain \/ YouDisconnect
    \/ ReadWorks \/ ReadFails \/ SyncDone \/ SyncRuns \/ Restart
Spec == Init /\ [][Next]_vars

\* ---- Rules

\* "Waiting for you to sign in" means a sign-in can still finish.
SignInCanFinish == status = "signin" => pending
\* "Reading your holdings" means something is reading them (or will, as soon as OpenTicker finishes starting).
SpinnerMeansWork == status = "fetching" => worker
\* The Review button opens something to review, or reads it again.
ReviewHasContent == status = "review" => (preview \/ ENABLED YouReviewLost)
\* Cancel and Remove do what they say on every row that shows them: the row stops waiting.
CancelWorks == /\ status \in {"signin", "fetching"} => ENABLED (YouCancel /\ status' \notin {"signin", "fetching", "review", "error"})
               /\ status \in {"auth", "error"} => ENABLED (YouDisconnect /\ status' = "none")
\* A synced account keeps its daily sync, or the row says why it can't (the sign-in expired).
KeepsSyncing == synced => status \in {"ok", "auth"} \/ (status = "fetching" /\ worker) \/ (status = "signin" /\ pending)
====
