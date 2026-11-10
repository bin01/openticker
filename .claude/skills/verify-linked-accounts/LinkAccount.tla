---- MODULE LinkAccount ----
\* One linked brokerage, as Settings, Accounts shows it: app/links.py on the server, app/static/links.js on the page.
\* status is the links row in SQLite and survives a restart; pending (links.PENDING), preview (links.PREVIEW) and
\* worker (the _fetch_async thread) live only in the server's memory. SKILL.md has the full map.
VARIABLES status, synced, pending, preview, worker
vars == <<status, synced, pending, preview, worker>>

\* status: "none" (no row), "signin", "fetching", "review", "ok", "auth", "error"
\* synced: links.synced is set (the link mirrored positions at least once)

Init == status = "none" /\ synced = FALSE /\ pending = FALSE /\ preview = FALSE /\ worker = FALSE

\* ---- you, in Settings: only the buttons linksSection() draws for each status

\* a preset's Add button -> connect(): PENDING[state] = ..., add_link(status="signin")
YouConnect == status = "none" /\ status' = "signin" /\ pending' = TRUE /\ synced' = FALSE
    /\ UNCHANGED <<preview, worker>>

\* the browser comes back -> callback(): PENDING.pop(state), exchange, put_secret, _fetch_async (status "fetching")
YouAllowInBrowser == status = "signin" /\ pending /\ status' = "fetching" /\ pending' = FALSE /\ worker' = TRUE
    /\ UNCHANGED <<synced, preview>>
\* callback() with ?error=access_denied, or the code exchange fails: status "error"
YouDenyInBrowser == status = "signin" /\ pending /\ status' = "error" /\ pending' = FALSE
    /\ UNCHANGED <<synced, preview, worker>>

\* Cancel on a signin/fetching row -> cancel(): disconnect() only if the link never synced
YouCancel == status \in {"signin", "fetching"}
    /\ IF synced THEN UNCHANGED vars
       ELSE status' = "none" /\ pending' = FALSE /\ preview' = FALSE /\ worker' = FALSE /\ UNCHANGED synced

\* Review -> Add -> apply(): PREVIEW.pop, mirror_link, status "ok", synced set
YouAdd == status = "review" /\ preview /\ status' = "ok" /\ synced' = TRUE /\ preview' = FALSE
    /\ UNCHANGED <<pending, worker>>
\* Review -> Don't add: cancel() on a first-time link; a link that synced before just closes the sheet
YouDontAdd == status = "review"
    /\ IF synced THEN UNCHANGED vars
       ELSE status' = "none" /\ preview' = FALSE /\ UNCHANGED <<synced, pending, worker>>

\* Try again on an error row -> retry(): _fetch_async
YouRetry == status = "error" /\ status' = "fetching" /\ worker' = TRUE /\ UNCHANGED <<synced, pending, preview>>
\* Remove on an error row -> cancel()
YouRemove == status = "error"
    /\ IF synced THEN UNCHANGED vars
       ELSE status' = "none" /\ UNCHANGED <<synced, pending, preview, worker>>
\* Sign in again on an auth row -> reconnect(): PENDING[state] = ..., status "signin"
YouSignInAgain == status = "auth" /\ status' = "signin" /\ pending' = TRUE /\ UNCHANGED <<synced, preview, worker>>
\* Disconnect -> Keep them / Remove them -> disconnect(): remove_link
YouDisconnect == status = "ok" /\ status' = "none" /\ synced' = FALSE /\ preview' = FALSE /\ pending' = FALSE
    /\ UNCHANGED worker

\* ---- the server

\* the _fetch_async thread: fetch() works -> PREVIEW[lid] = got, status "review"
ReadWorks == worker /\ worker' = FALSE /\ preview' = TRUE /\ status' = "review" /\ UNCHANGED <<synced, pending>>
\* fetch() raises -> status "auth" (AuthNeeded) or "error"
ReadFails == worker /\ worker' = FALSE /\ status' \in {"error", "auth"} /\ UNCHANGED <<synced, pending, preview>>
\* the daily sync (loop -> due -> sync) or Sync now: works, or the provider wants a new sign-in (status "auth");
\* any other failure keeps status "ok" with an error line
SyncRuns == status = "ok" /\ status' \in {"ok", "auth"} /\ UNCHANGED <<synced, pending, preview, worker>>
\* OpenTicker quits and starts again: memory is gone, the row stays
Restart == (pending \/ preview \/ worker) /\ pending' = FALSE /\ preview' = FALSE /\ worker' = FALSE
    /\ UNCHANGED <<status, synced>>

Next == YouConnect \/ YouAllowInBrowser \/ YouDenyInBrowser \/ YouCancel \/ YouAdd \/ YouDontAdd
    \/ YouRetry \/ YouRemove \/ YouSignInAgain \/ YouDisconnect
    \/ ReadWorks \/ ReadFails \/ SyncRuns \/ Restart
Spec == Init /\ [][Next]_vars

\* ---- Rules

\* "Waiting for you to sign in" means a sign-in can still finish.
SignInCanFinish == status = "signin" => pending
\* "Reading your holdings" means something is reading them.
SpinnerMeansWork == status = "fetching" => worker
\* The Review button opens something to review.
ReviewHasContent == status = "review" => preview
\* Cancel and Remove do what they say on every row that shows them.
CancelWorks == status \in {"signin", "fetching", "error"} => ~synced
\* A synced account keeps its daily sync, or the row says why it can't (the sign-in expired).
KeepsSyncing == synced => status \in {"ok", "auth"} \/ (status = "fetching" /\ worker) \/ (status = "signin" /\ pending)
====
