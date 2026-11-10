---
name: verify-workbench
description: Model-checks Tick's workbench with Claude Code, that the workbench is switched off only after the sandbox failed (never after a plain "signed out" or "usage limit" error) and that Tick is promised scipy and matplotlib only once the toolbox is installed. Use when changing app/workbench.py (build, _build, python, claude_ready, claude_failed, sandbox_failed, note), the sandbox fallback in runs._work, agent.PLAIN_FAILURE, or the bench argument of agent.build_prompt.
metadata:
  synced: 1d01cf8
  covers: app/workbench.py app/runs.py app/agent.py
  models: SandboxWorks.cfg NoSandbox.cfg
  known:
  tests: tests.test_state_machines.Workbench tests.test_workbench.Settings
---

# Verify Tick's workbench

When Tick answers with Claude Code, it gets a folder to run code in, inside Claude Code's macOS sandbox, with a Python toolbox that installs in the background (app/workbench.py). If the sandbox doesn't start, `runs._work` answers again without the workbench and switches it off for an hour. `Workbench.tla` models the toolbox install, that switch, Claude Code's own trouble and restarts, for a Mac where the sandbox works (`SandboxWorks.cfg`) and one where it doesn't (`NoSandbox.cfg`). The tests run the real `_work` with a fake agent.

## The rules

| Rule | In plain words | If it broke |
| --- | --- | --- |
| `OffOnlyAfterSandboxTrouble` | The workbench is switched off only after the sandbox failed, or after an unexplained quick error that could be the sandbox failing, never after an error that says plainly what went wrong. | Signing out or hitting the plan limit once quietly takes away Tick's ability to run code for an hour, and answers get worse with no sign why. |
| `PromisedToolsExist` | Tick is promised scipy, matplotlib and `pip install` only once the toolbox is installed. | Tick writes code that imports scipy, it fails, and the answer is a stack of errors or made-up numbers. |

## Run it

```sh
python3 .claude/formal/verify.py workbench
```

About ten seconds. Needs Java 11 or later (`brew install openjdk`); downloads TLC once; uses `.venv` for the tests if present. Exits 0 when every rule holds and the tests pass. `agent.py` and `runs.py` are large and covered only in part, so the runner's "changed since" line can be noise: check whether the change touches a function in the map.

## Does your change touch this?

Yes if it changes any function in the map below, the 30-second `quick_fail` test, `PLAIN_FAILURE`, `RETRY_AFTER`, when `.ready` is written, or what `note()` says before the toolbox is ready.

## The map: model step to code

| Action | Code |
| --- | --- |
| `ToolboxBuilt` | `workbench._build`: `uv venv` and `pip install` (bytecode compiled, pip included), `_warm()` (matplotlib's font list), then `TOOLBOX/.ready` and `state["toolbox"] = "ready"` |
| `ToolboxFails` | `_build`'s `except`: `toolbox = "failed"`, `failed_at = now` |
| `AnHourPasses` | `RETRY_AFTER` seconds since `failed_at` or `claude_off` |
| `AgentChanges` | Claude Code signs out, hits its limit, crashes, comes back (outside OpenTicker) |
| `YouAsk` | one question with Claude Code, `runs._work`: `bench` from `claude_ready()` (which turns `claude_ok` back on after an hour); `workbench.build()` (retries a failed install after an hour, finds a ready one on disk); `build_prompt(bench=...)` → `note()` picks the full or the early note by `python()`; then `go()`. If there's no text and the error is `sandbox_failed(...)` or a `quick_fail` (inside 30 s and not `agent.plain_failure`), `claude_failed()` and `go(None, None)` without the workbench. |
| `Restart` | the process starts again: `state` is rebuilt (`claude_ok` True, toolbox "missing"), `workbench.ensure()` → `build()` |
| `Note(tb)` | `workbench.note()`: `NOTE` when `python()` finds the toolbox (a `.ready` written at `TOOLBOX_VERSION`; an older toolbox counts as missing and is made again), else the "still being set up" variant |

The agent states: "plain" is an error matched by `agent.PLAIN_FAILURE`; "odd" is any other error inside 30 seconds with no text, which `_work` can't tell from a sandbox that didn't start. Codex's workbench (its own folder as its only writable root, no `--add-dir`) has no such switch and isn't modeled. Not modeled: the proxy, the folder pruning, what code runs inside the sandbox, and that the shared toolbox is read-only to it (`claude_settings` writes only the conversation's folder; `env` sends `pip install` and caches there): that's `tests.test_workbench` (`Settings.test_toolbox_is_read_only`, `Settings.test_installs_and_caches_stay_in_the_conversation`).

## Findings on the current code

None. Both rules hold for both configs. The earlier audit's bugs here (a plain error switched the workbench off until a restart; the note promised scipy too early) were fixed in #3 and these rules keep them fixed.

One design choice the model makes visible rather than a bug: an unexplained quick error ("odd") does switch the workbench off for an hour, on purpose, because an older Claude Code that rejects the sandbox settings looks exactly like that.

## Reading a result

When a rule breaks, the runner prints TLC's path to it as numbered steps with only the variables that changed: it is the shortest way the code can break that rule. Retell it in plain words, one step per line, before acting on it.

Before calling a broken rule a bug, replay its path on the real code one action per step: the `Workbench` tests show how (`FakeRun` scripts what Claude Code emits, `workbench.state` is set directly, `claude_off` is moved back an hour). If the code doesn't do what the path says, the model is wrong.

## When you change the code on purpose

1. Change the code.
2. Change the matching action in `Workbench.tla` and the map here.
3. Change a rule only if the promise itself changed, and say why in the commit. Never weaken a rule to make it pass.
4. Run the check; add a `Workbench` test for any new path.
5. Move `synced` to the new commit only after reading the covered functions at that commit and confirming the model describes them.

## How the check was shown to catch breaks

At 3218198, with `not agent.plain_failure(...)` removed from `quick_fail` in `runs._work`, the check failed twice over: `test_signed_out_keeps_the_workbench` failed on the real code, and with the same change mirrored in `YouAsk` (a "plain" error takes the fallback branch), `OffOnlyAfterSandboxTrouble` broke in two steps: Claude Code signs out, you ask, and the workbench is off for an hour. `PromisedToolsExist` breaks if `Note` ignores the toolbox (always the full note): you ask while it installs.
