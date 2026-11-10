---
name: verify-linked-accounts
description: Model-checks linked brokerage accounts (Monarch, Interactive Brokers, Robinhood, any MCP server), that every row in Settings, Accounts means what it says across restarts and its buttons work, and that syncing never loses a working sign-in, including two syncs at once with a provider that rotates refresh tokens. Use when changing app/links.py (connect, callback, _fetch_async, preview, apply, sync, retry, reconnect, disconnect, cancel, _session, loop, due), mcp_client.refresh, the Keychain helpers, or linksSection and the review sheet in app/static/links.js.
metadata:
  synced: 1d01cf8
  covers: app/links.py app/mcp_client.py app/static/links.js
  models: LinkAccount.cfg OneSync.cfg NoRotation.cfg Overlap.cfg LostReply.cfg
  known: LostReply.cfg:StaysSignedIn LostReply.cfg:KeychainWorks
  tests: tests.test_links
---

# Verify linked accounts

Two models, one per question.

`LinkAccount.tla` follows one link through Settings, Accounts: connect, sign in, review, add, sync, sign in again, cancel, disconnect, and OpenTicker restarting at any point. The row's status is in SQLite and survives a restart; the sign-in in progress (`links.PENDING`), what was found (`links.PREVIEW`) and the reading thread live only in memory.

`TokenRefresh.tla` follows the sign-in token through syncs that can overlap (the daily sync and Sync now, each on its own thread). `_session` refreshes the token when it's about to run out and saves the reply to the Keychain. Configs: `OneSync` (one sync at a time, rotating tokens), `NoRotation` (two at once, a provider that keeps refresh tokens), `Overlap` (two at once, rotating), `LostReply` (one at a time, rotating, the reply can be lost).

`tests.test_links` runs the real code against a fake provider on this machine, with a switch (`fake.rotate`) for rotating refresh tokens.

## The rules

| Rule | In plain words | If it broke |
| --- | --- | --- |
| `SignInCanFinish` | "Waiting for you to sign in" means a sign-in can still finish. | The row waits forever; the browser says the link expired. |
| `SpinnerMeansWork` | "Reading your holdings" means something is reading them, or will as soon as OpenTicker finishes starting. | A spinner that never stops. |
| `ReviewHasContent` | The Review button opens something to review, or reads it again. | Review opens an empty sheet; Add says "Nothing to add yet". |
| `CancelWorks` | Cancel and Remove do what they say on every row that shows them: the row stops waiting. | The button does nothing, and the row can't be got rid of. |
| `KeepsSyncing` | A synced account keeps its daily sync, or the row says why it can't. | Positions quietly stop updating. |
| `StaysSignedIn` | Once syncs finish, OpenTicker isn't asking you to sign in again while the provider would still accept it. | "The sign-in expired" for no reason, and the daily sync stops until you sign in again. |
| `KeychainWorks` | Between syncs, the Keychain holds a refresh token the provider accepts. | The next sync fails however the row looks. |

## Run it

```sh
python3 .claude/formal/verify.py linked-accounts
```

About twenty seconds. Needs Java 11 or later (`brew install openjdk`); downloads TLC once; uses `.venv` for the tests if present. Exits 0 when every rule holds except the known findings below, and the tests pass.

## Does your change touch this?

Yes if it changes any function in the maps, the statuses a link can have, which buttons `linksSection` draws for a status, what lives in memory versus SQLite, when the token is refreshed or saved, or who can call `sync` at the same time.

## The map: LinkAccount

| Action | Code |
| --- | --- |
| `StartRead` | `_refresh_async`: a link that synced before goes to `_sync_async` (sync straight away), a new one to `_fetch_async` (read for review); both set status "fetching" and add the link to `_reading` |
| `YouConnect` | a preset's button → `connect()`: `PENDING[state]`, `add_link(status="signin")` |
| `YouAllowInBrowser` | `callback()`: `PENDING.pop(state)`, `M.exchange`, `put_secret`, `_refresh_async` |
| `YouDenyInBrowser` | `callback()` with `error`, or the exchange fails: "auth" for a synced link, "error" for a new one |
| `YouCancel` | Cancel (signin/fetching) → `cancel()`: a never-synced link is disconnected; a synced one drops `PENDING`/`PREVIEW` and goes to "auth" (from signin) or "ok" |
| `YouReviewLost` | Review with the preview gone (`openLinkReview` gets none) → `retry()` → `_refresh_async`, and the sheet reopens when it's ready |
| `YouAdd` | Review → Add → `apply()`: `PREVIEW.pop`, `mirror_link`, status "ok", `synced` |
| `YouDontAdd` | Review → Don't add on a first-time link → `cancel()` |
| `YouRetry` | Try again → `retry()` → `_refresh_async` |
| `YouSignInAgain` | Sign in again → `reconnect()`: old `PENDING` entries for the link dropped, a new one added, status "signin" |
| `YouDisconnect` | `disconnect()`: Disconnect (ok, or auth on a synced link) or Remove (error on a synced link) → Keep or Remove them; Remove on an error or auth row of a never-synced link, straight away (`linkAct("remove")`, positions not kept). A read still running sees the row gone and writes nothing |
| `ReadWorks`, `ReadFails` | `_fetch_async` thread: `PREVIEW[lid] = got`, status "review"; or "auth"/"error" |
| `SyncDone` | `_sync_async` thread: `sync()` → `apply()` sets "ok"; `AuthNeeded` sets "auth"; any other failure "ok" with an error line |
| `SyncRuns` | `loop()` → `due()` → `sync()`, or Sync now |
| `Restart` | `bind()` → `_after_restart()`: "signin" becomes "auth", "fetching" and "review" become "fetching"; `loop()` → `_read_again()` starts a read for each "fetching" row once prices have loaded. The model folds the two into one step, so the spinner shows while OpenTicker is still starting (longer if Yahoo is down at start-up). |

## The map: TokenRefresh

| Action | Code |
| --- | --- |
| `Start` | `sync()` → `fetch()` takes the link's lock (`_fetch_locks`), held until the read ends, then `_fetch()` → `get_secret(lid)`; the access token runs out within 60 s |
| `Refresh` | `_session`: `M.refresh(...)` → `_token`; `invalid_grant` raises `AuthNeeded`, and `sync()` sets status "auth"; a provider that keeps refresh tokens returns none, and `refresh()` keeps the old one |
| `ReplyLost` | the provider acted but the reply never arrived (time-out, Wi-Fi, OpenTicker quit): `MCPError`, status stays "ok" |
| `Save` | `_session`: `put_secret(link["id"], sec)`, then the holdings are read and `apply()` sets status "ok" |

Not modeled: the access token itself (only refresh tokens), the provider expiring or revoking a sign-in (so any "auth" in the model is OpenTicker's doing), the 401 retry path in `_session` (same steps as `Refresh` then `Save`), what's read from the provider (`normalize`, `pick_tools`: `tests.test_links.Replies`), and security checks (`tests.test_links`).

## Findings on the current code

1. **A lost refresh reply signs you out, with a provider that rotates refresh tokens** (`LostReply.cfg`, known). If the provider rotates the token and its reply never arrives, the Keychain keeps a retired token and the next sync asks you to sign in again. No client can fully avoid this; it stays listed so a change that makes it worse (say, retrying a refresh in a loop) is noticed.

Fixed in #16: the three audit-3 bugs (the link's memory didn't survive a restart; Cancel and Remove did nothing on a synced link; a synced link could stop syncing for good), and two syncs at once signing you out with a rotating provider (`Overlap.cfg`), which the per-link lock in `fetch()` prevents. `test_two_syncs_at_once_stay_signed_in` runs the overlap on the real code and fails without the lock.

## Reading a result

When a rule breaks, the runner prints TLC's path to it as numbered steps with only the variables that changed: it is the shortest way the code can break that rule. Retell it in plain words, one step per line, before acting on it.

Before calling a broken rule a bug, replay its path on the real code one action per step. `tests.test_links.Links` shows how: `sign_in()` drives the fake provider, `links.PENDING.clear()`, `links.PREVIEW.clear()` and `links._after_restart()` stand in for a restart, `self.fake.rotate = True` makes the provider rotate, and setting `sec["token"]["expires_at"] = 0` forces a refresh. To force an overlap, wrap `M.refresh` so both syncs read the Keychain before either refreshes. If the code doesn't do what the path says, the model is wrong.

## When you change the code on purpose

1. Change the code.
2. Change the matching actions in the model and the map here.
3. Change a rule only if the promise itself changed, and say why in the commit. Never weaken a rule to make it pass.
4. Run the check. A known finding that now holds makes the runner fail until you take it out of `known` and out of the findings above.
5. Add a test to `tests.test_links` for any new path.
6. Move `synced` to the new commit only after reading the covered functions at that commit and confirming the models describe them.

## How the check was shown to catch breaks

At 3218198, with `put_secret` removed after the refresh at the top of `_session` (a new refresh token never saved), the check failed twice over: `test_rotated_refresh_token_is_kept` failed on the real code, and with the same change mirrored in `Save` (the Keychain left as it was), `OneSync.cfg` broke both `StaysSignedIn` and `KeychainWorks`: one sync refreshes and doesn't save, the next one is refused. The five `LinkAccount` rules broke on the code before #16, each path replayed on the real code in the third audit; `Overlap.cfg` broke before the per-link lock, and `test_two_syncs_at_once_stay_signed_in` fails with the lock removed.
