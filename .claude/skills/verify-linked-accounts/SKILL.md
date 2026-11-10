---
name: verify-linked-accounts
description: Model-checks linked brokerage accounts (Monarch, Interactive Brokers, Robinhood, any MCP server), that every row in Settings, Accounts means what it says across restarts and its buttons work, and that syncing never loses a working sign-in, including two syncs at once with a provider that rotates refresh tokens. Use when changing app/links.py (connect, callback, _fetch_async, preview, apply, sync, retry, reconnect, disconnect, cancel, _session, loop, due), mcp_client.refresh, the Keychain helpers, or linksSection and the review sheet in app/static/links.js.
metadata:
  synced: 3218198
  covers: app/links.py app/mcp_client.py app/static/links.js
  models: LinkAccount.cfg OneSync.cfg NoRotation.cfg Overlap.cfg LostReply.cfg
  known: LinkAccount.cfg:SignInCanFinish LinkAccount.cfg:SpinnerMeansWork LinkAccount.cfg:ReviewHasContent LinkAccount.cfg:CancelWorks LinkAccount.cfg:KeepsSyncing Overlap.cfg:StaysSignedIn LostReply.cfg:StaysSignedIn LostReply.cfg:KeychainWorks
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
| `SpinnerMeansWork` | "Reading your holdings" means something is reading them. | A spinner that never stops. |
| `ReviewHasContent` | The Review button opens something to review. | Review opens an empty sheet; Add says "Nothing to add yet". |
| `CancelWorks` | Cancel and Remove do what they say on every row that shows them. | The button does nothing, and the row can't be got rid of. |
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
| `YouConnect` | a preset's button → `connect()`: `PENDING[state]`, `add_link(status="signin")` |
| `YouAllowInBrowser` | `callback()`: `PENDING.pop(state)`, `M.exchange`, `put_secret`, `_fetch_async` (status "fetching") |
| `YouDenyInBrowser` | `callback()` with `error`, or the exchange fails: status "error" |
| `YouCancel` | Cancel on a signin/fetching row → `cancel()`, which disconnects only a link that never synced |
| `YouAdd` | Review → Add → `apply()`: `PREVIEW.pop`, `mirror_link`, status "ok", `synced` |
| `YouDontAdd` | Review → Don't add: `cancel()` the first time (`firstTime` in links.js), otherwise just closes |
| `YouRetry` | Try again → `retry()` → `_fetch_async` |
| `YouRemove` | Remove on an error row → `cancel()` |
| `YouSignInAgain` | Sign in again → `reconnect()`: `PENDING[state]`, status "signin" |
| `YouDisconnect` | Disconnect → Keep or Remove them → `disconnect()` |
| `ReadWorks`, `ReadFails` | the `_fetch_async` thread: `PREVIEW[lid] = got`, status "review"; or status "auth"/"error" |
| `SyncRuns` | `loop()` → `due()` → `sync()`, or Sync now: status stays "ok" (an error line on failure) or becomes "auth" on `AuthNeeded` |
| `Restart` | the process starts again: `PENDING`, `PREVIEW` and the thread are gone, the row stays |

## The map: TokenRefresh

| Action | Code |
| --- | --- |
| `Start` | `sync()` → `fetch()` → `get_secret(lid)`; the access token runs out within 60 s |
| `Refresh` | `_session`: `M.refresh(...)` → `_token`; `invalid_grant` raises `AuthNeeded`, and `sync()` sets status "auth"; a provider that keeps refresh tokens returns none, and `refresh()` keeps the old one |
| `ReplyLost` | the provider acted but the reply never arrived (time-out, Wi-Fi, OpenTicker quit): `MCPError`, status stays "ok" |
| `Save` | `_session`: `put_secret(link["id"], sec)`, then the holdings are read and `apply()` sets status "ok" |

Not modeled: the access token itself (only refresh tokens), the provider expiring or revoking a sign-in (so any "auth" in the model is OpenTicker's doing), the 401 retry path in `_session` (same steps as `Refresh` then `Save`), what's read from the provider (`normalize`, `pick_tools`: `tests.test_links.Replies`), and security checks (`tests.test_links`).

## Findings on the current code

1. **The link's memory doesn't survive a restart** (`SignInCanFinish`, `SpinnerMeansWork`, `ReviewHasContent`). Quit OpenTicker while a row says "Waiting for you to sign in", "Reading your holdings" or "Ready. Review", and after the restart it says the same thing with nothing behind it. A new link stuck in "review" can't be removed, and the provider can't be linked again ("already linked").
2. **Cancel and Remove do nothing on a link that synced before** (`CancelWorks`). Path: link, add, the sign-in expires, Sign in again, then Cancel. `cancel()` only disconnects links that never synced.
3. **A synced link can stop syncing for good** (`KeepsSyncing`). Same path, then deny in the browser: status "error" with positions from before, Remove does nothing, and the daily sync needs status "ok". Signing in again on a synced link also goes through Review, and closing it leaves the link in "review", which never syncs.

These three were found in the third state machine audit and are fixed on the branch of the open pull request #16 ("Fix the state machine bugs in linked accounts, signals, the ticker tape and adding a purchase"). When it merges, update `LinkAccount.tla` to the new code (statuses survive a restart, `cancel()` works on synced links, a reconnect syncs straight away), check that these rules hold, and empty them from `known`.

4. **Two syncs at once can sign you out, with a provider that rotates refresh tokens** (`Overlap.cfg:StaysSignedIn`). Path: the daily sync and Sync now both read the Keychain; the first refreshes (the provider retires the old refresh token), saves the new one and finishes; the second refreshes with the old one, gets `invalid_grant`, and sets the row to "The sign-in expired" while the Keychain holds a token that works. The daily sync then stops (`due()` needs status "ok") until you sign in again. Replayed on the real code with the fake provider rotating tokens and the two refreshes held in that order. Whether Monarch, Interactive Brokers or Robinhood rotate refresh tokens isn't known; `NoRotation` shows the same overlap is harmless when they don't. A fix: one lock per link around `_session`'s refresh-and-save, and re-reading the Keychain inside it before refreshing.
5. **A lost refresh reply signs you out, with a rotating provider** (`LostReply.cfg`). If the provider rotates the token and the reply never arrives, the Keychain keeps a retired token. No client can fully avoid this; it's listed so a change that makes it worse (say, retrying a refresh in a loop) is noticed.

None are fixed here: product code changes need the person's go-ahead.

## Reading a result

Read every TLC result with the pstack `/statechart` skill: it shows a broken rule as its shortest path in plain words, and draws the link's states when everything holds. The runner prints TLC's path as numbered steps with only the variables that changed.

Before calling a broken rule a bug, replay its path on the real code one action per step. `tests.test_links.Links` shows how: `sign_in()` drives the fake provider, `links.PENDING.clear()` and `links.PREVIEW.clear()` stand in for a restart, `self.fake.rotate = True` makes the provider rotate, and setting `sec["token"]["expires_at"] = 0` forces a refresh. To force an overlap, wrap `M.refresh` so both syncs read the Keychain before either refreshes. If the code doesn't do what the path says, the model is wrong.

## When you change the code on purpose

1. Change the code.
2. Change the matching actions in the model and the map here.
3. Change a rule only if the promise itself changed, and say why in the commit. Never weaken a rule to make it pass.
4. Run the check. A known finding that now holds makes the runner fail until you take it out of `known` and out of the findings above.
5. Add a test to `tests.test_links` for any new path.
6. Move `synced` to the new commit only after reading the covered functions at that commit and confirming the models describe them.

## How the check was shown to catch breaks

At 3218198, with `put_secret` removed after the refresh at the top of `_session` (a new refresh token never saved), the check failed twice over: `test_rotated_refresh_token_is_kept` failed on the real code, and with the same change mirrored in `Save` (the Keychain left as it was), `OneSync.cfg` broke both `StaysSignedIn` and `KeychainWorks`: one sync refreshes and doesn't save, the next one is refused. The five `LinkAccount` rules each break on the current code (the findings), and each path was replayed on the real code in the third audit.
