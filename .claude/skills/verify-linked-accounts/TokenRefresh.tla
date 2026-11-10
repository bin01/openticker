---- MODULE TokenRefresh ----
\* A linked account's sign-in across syncs that can be asked for at once: the daily sync (links.loop -> sync), Sync now
\* (POST /api/me/links/sync -> sync) and a read after a new sign-in, each one fetch() -> _session(). _session refreshes the token when it is about to
\* run out (mcp_client.refresh) and saves the reply in the Keychain (put_secret). SKILL.md has the full map.
EXTENDS Naturals, FiniteSets

CONSTANTS
    Syncs,      \* the syncs that can overlap, e.g. {1, 2}
    Rotates,    \* the provider issues a new refresh token on every refresh and retires the one it was given
    LoseReply,  \* a refresh reply can be lost (time-out, Wi-Fi drop, OpenTicker quits) after the provider acted on it
    MaxToken    \* bound on refresh tokens issued, to keep the model finite (see Bound)

VARIABLES
    live,       \* refresh tokens the provider accepts
    issued,     \* the newest refresh token the provider issued
    keychain,   \* the refresh token saved in the Keychain (get_secret/put_secret)
    pc,         \* each sync's step
    held,       \* the refresh token each sync read from the Keychain
    got,        \* the refresh token each sync got back from the provider
    status      \* the links row: "ok", or "auth" after AuthNeeded (the row asks you to sign in again)

vars == <<live, issued, keychain, pc, held, got, status>>

Init == live = {1} /\ issued = 1 /\ keychain = 1 /\ pc = [s \in Syncs |-> "idle"] /\ held = [s \in Syncs |-> 0]
    /\ got = [s \in Syncs |-> 0] /\ status = "ok"

\* fetch() takes the link's lock (_fetch_locks[lid]), which it holds until this read is over, then _fetch():
\* sec = get_secret(lid); the access token is about to run out (expires_at < now + 60)
Start(s) == pc[s] = "idle" /\ status = "ok"
    /\ (\A o \in Syncs \ {s} : pc[o] = "idle")
    /\ pc' = [pc EXCEPT ![s] = "read"] /\ held' = [held EXCEPT ![s] = keychain]
    /\ UNCHANGED <<live, issued, keychain, got, status>>

\* M.refresh(): the provider checks the refresh token. A good one gets a new access token, and a new refresh token
\* when the provider rotates them (tok["refresh_token"] falls back to the old one when it doesn't).
Refresh(s) == pc[s] = "read"
    /\ (IF held[s] \in live
       THEN /\ issued' = (IF Rotates THEN issued + 1 ELSE issued)
            /\ live' = (IF Rotates THEN (live \ {held[s]}) \cup {issued + 1} ELSE live)
            /\ got' = [got EXCEPT ![s] = IF Rotates THEN issued + 1 ELSE held[s]]
            /\ pc' = [pc EXCEPT ![s] = "save"]
            /\ UNCHANGED status
       ELSE \* invalid_grant -> AuthNeeded -> sync() sets status "auth"
            /\ pc' = [pc EXCEPT ![s] = "idle"] /\ status' = "auth"
            /\ UNCHANGED <<live, issued, got>>)
    /\ UNCHANGED <<keychain, held>>

\* the provider rotated the token but the reply never arrives: MCPError, sync() keeps status "ok" with an error
ReplyLost(s) == LoseReply /\ pc[s] = "save"
    /\ pc' = [pc EXCEPT ![s] = "idle"]
    /\ UNCHANGED <<live, issued, keychain, held, got, status>>

\* put_secret(link["id"], sec) with the new token; then the holdings are read and apply() sets status "ok"
Save(s) == pc[s] = "save"
    /\ keychain' = got[s] /\ pc' = [pc EXCEPT ![s] = "idle"] /\ status' = "ok"
    /\ UNCHANGED <<live, issued, held, got>>

Idle == \A s \in Syncs : pc[s] = "idle"

Rest == status = "auth" /\ Idle /\ UNCHANGED vars

Next == (\E s \in Syncs : Start(s) \/ Refresh(s) \/ ReplyLost(s) \/ Save(s)) \/ Rest
Spec == Init /\ [][Next]_vars

\* TLC stops exploring once this many refresh tokens exist
Bound == issued < MaxToken

\* ---- Rules

\* Once syncs finish, OpenTicker isn't asking you to sign in again while the provider would still accept it.
\* (This model has no expiry or revocation by the provider, so any "auth" here is OpenTicker's own doing.)
StaysSignedIn == Idle => status = "ok"

\* Between syncs, the Keychain holds a refresh token the provider accepts.
KeychainWorks == Idle => keychain \in live
====
