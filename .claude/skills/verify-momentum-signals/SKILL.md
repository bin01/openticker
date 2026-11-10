---
name: verify-momentum-signals
description: Model-checks the Screener's Momentum signals, that only one scan of about 600 stocks runs at a time however many pages ask, and that the page keeps a moving progress bar moving and picks up new scores after a close. Use when changing signals_payload or signals_scan in app/server.py (SIG, _sig_lock, the stale test, failAt), or SIG, sigWait, loadSignals and renderSignals in app/static/pages.js.
metadata:
  synced: 1d01cf8
  covers: app/server.py app/static/pages.js
  models: Signals.cfg
  known:
  tests: tests.test_state_machines.SignalsScan tests.test_signals
---

# Verify momentum signals

The server scores every stock in the big funds once per close, in a background scan of about a minute (`signals_scan`); `GET /api/signals` answers with the latest scores and starts a scan when they're stale (`signals_payload`). The page keeps its copy in `SIG` and checks back every 3 seconds while a scan runs (`sigWait`). `Signals.tla` models the server, the page, you coming and going, a second device asking at the same time, and new closes. `tests.test_state_machines.SignalsScan` fires four requests at once at the real `signals_payload`; `tests.test_signals` covers the score itself.

## The rules

| Rule | In plain words | If it broke |
| --- | --- | --- |
| `OneScanAtATime` | Only one scan runs at a time. | Two or more scans download a year of prices for 600 stocks at once, Yahoo starts refusing, and both can fail. |
| `ProgressMoves` | A progress bar on screen keeps moving: the page is still checking. | The bar freezes; the scores never appear until a reload. |
| `GetsNewClose` | After a new close, the open screener gets the new scores, within five minutes. | The screener shows yesterday's ratings until a reload. |

## Run it

```sh
python3 .claude/formal/verify.py momentum-signals
```

About ten seconds. Needs Java 11 or later (`brew install openjdk`); downloads TLC once; uses `.venv` for the tests if present. Exits 0 when every rule holds except the known findings below, and the tests pass. `server.py` and `pages.js` are large and covered only in part, so the runner's "changed since" line is often noise: check whether the change touches a function in the map.

## Does your change touch this?

Yes if it changes any function in the map, when scores count as stale, when the page fetches `/api/signals`, when `sigWait` is set or cleared, or how leaving the screener stops checking.

## The map: model step to code

| Action | Code |
| --- | --- |
| `Answer` | the page's request: `loadSignals()` → `signals_payload`; stale with no scan running → under `_sig_lock`, `SIG["running"] = True` and a `signals_scan` thread, unless `failAt` is under 300 s old (answers with the last error); the page sets `SIG`, and `sigWait` for 3 s if `SIG.running` |
| `Ask`, `TakeLock` | another device's request: `stale` worked out outside the lock, then the check-and-start inside `_sig_lock` |
| `YouOpenScreener` | Screener → Momentum signals: `renderSignals` loads when `SIG` is null, and otherwise calls `sigCheck()` (load again if a scan is running with no `sigWait` timer, or if the last load is over five minutes old) |
| `Recheck` | the 60-second interval while the page is visible: `sigCheck()` (time is abstract, so "five minutes old" can be any time) |
| `YouLeave` | any other page or screen |
| `PollFires` | the `sigWait` timer (sets `sigWait = null`): reloads only if `sigHere()`, otherwise stops |
| `YouRetry` | Try again on an error: `SIG = null`, then `loadSignals` |
| `ScanEnds` | `signals_scan` ends: `SIG.update(rows=..., running=False)`, or the `except` branch (error, `failAt`), then `finally: running = False` |
| `NewClose` | `signals_payload` finds the scores stale: a new close, six hours, or, after the close, scores still dated before today 15 minutes on |

Not modeled: the 5-second wait while the first launch is still fetching holdings (same shape as `PollFires`), the `partial` re-scan, which stocks are scored, and the score (`tests.test_signals`).

## Findings on the current code

None open. Every rule holds.

Fixed in #16: leaving the screener mid-scan froze the progress bar (`ProgressMoves`), and an open screener never picked up a new close (`GetsNewClose`). `sigCheck()` on each render and every minute keeps both true.

## Reading a result

Read every TLC result with the pstack `/statechart` skill: it shows a broken rule as its shortest path in plain words, and draws how the screener moves between states when everything holds. The runner prints TLC's path as numbered steps with only the variables that changed.

Before calling a broken rule a bug, replay its path on the real code one action per step: the server side as in `SignalsScan` (patch `server.signals_scan`, call `signals_payload`), the page side in a browser with the server running (open Screener → Momentum signals, leave, come back). If the code doesn't do what the path says, the model is wrong.

## When you change the code on purpose

1. Change the code.
2. Change the matching action in `Signals.tla` and the map here.
3. Change a rule only if the promise itself changed, and say why in the commit. Never weaken a rule to make it pass.
4. Run the check; add to `SignalsScan` for any new server path.
5. Move `synced` to the new commit only after reading the covered functions at that commit and confirming the model describes them.

## How the check was shown to catch breaks

At 3218198, with `not SIG["running"]` removed from the check in `signals_payload`, the check failed twice over: `test_one_scan_at_a_time` failed on the real code (four requests, four scans), and with the same change mirrored in `TakeLock` (start a scan whatever is running), `OneScanAtATime` broke: the page starts a scan, the phone asks, a second scan starts. The model's `Bound` constraint keeps it finite when a change like this lets scans pile up.
