---
name: verify-tick-answers
description: Model-checks that every question to Tick gets exactly one reply in its conversation, however OpenTicker stops and restarts mid-answer, and that the page ends a question only when the log does. Use when changing app/runs.py (start, _work, _finish, recover, _close_finished, follow), askDrive or askFollow in app/static/ask.js, or the run and chat functions in app/personal.py.
metadata:
  synced: 1d01cf8
  covers: app/runs.py app/static/ask.js
  models: TickAnswer.cfg
  known:
  tests: tests.test_state_machines.Restart
---

# Verify Tick's answers

An answer is a log (app/runs.py). The agent appends to it, the page reads it, and OpenTicker can stop between any two writes: quit, `openticker update`, a crash, the Mac sleeping. `TickAnswer.tla` models one question through every such stop with TLC, and `tests.test_state_machines.Restart` runs the real code through the same restarts.

## The rules

| Rule | In plain words | If it broke |
| --- | --- | --- |
| `OneAnswer` | A question never gets two answers in its conversation. | The conversation shows the same answer twice, and Tick's history is wrong for the next question. |
| `EveryQuestionAnswered` | Every question gets a reply in its conversation: an answer, or why there isn't one. | The question sits in the conversation with nothing under it, forever. |
| `PageEndsWithTheLog` | The page ends a question only once the log says it ended. | The page shows "No answer came back" while the answer is still being written. |

## Run it

```sh
python3 .claude/formal/verify.py tick-answers
```

About ten seconds. It needs Java 11 or later (`brew install openjdk`), downloads TLC once, and uses `.venv` for the tests if there is one (see "Running without the installer" in AGENTS.md). It prints which covered files changed since the commit in `synced`, the result of each rule, and the tests. It exits 0 when every rule holds except the known findings below, and the tests pass.

## Does your change touch this?

Yes if it changes any line named in the map below, the order of writes in `_finish` or `recover`, what `personal.runs_open()` returns, how `follow()` ends a stream, or how `askDrive` decides to stop reading. Then run the check before and after, and bring the model in line with the code first (next section).

## The map: model step to code

Every action in `TickAnswer.tla` is one step in the code. One step means one write that a stop can't split.

| Action | Code |
| --- | --- |
| `YouAsk` | `POST /api/ask` → `runs.start`: `personal.run_new` with status "running" |
| `PromptSaved` | `_work`: `personal.run_set(spec=...)` after `build_prompt` (a stop before it leaves no prompt to resume) |
| `EndSaved` | `_finish`: `lv.append("end")` then `lv.flush()` |
| `AnswerSaved` | `_finish`: `personal.chat_add(...)` |
| `RunClosed` | `_finish`: `personal.run_set(status=...)`; also the last line of `_close_finished`. Stop (`runs.stop`) takes the same path. |
| `OpenTickerStops` | the process ends; `_live` and `Live.stopped` are gone, the page's stream drops |
| `ComesBackCloses` | `recover`: the saved log has "end" → `_close_finished` adds the answer only if the conversation has none newer than `started` |
| `ComesBackGivesUp` | `recover`: `resumes >= 2` or no `spec["prompt"]` → `run_events_add(... "end" GAVE_UP)` |
| `GiveUpTold` | `recover`: `personal.chat_add(... GAVE_UP)`, before closing the run; then `run_set(status="error")` is `RunClosed` |
| `ComesBackResumes` | `recover`: `run_set(resumes=+1)`, `_work(resume=True)` on the same log |
| `ComesBackIdle` | a closed run isn't in `runs_open()`, so start-up leaves it alone |
| `Reattach`, `ShowEnd` | `askDrive`: after a drop, fetch `/api/ask/run?after=0` again; stop reading at "end" (`runs.follow` sends it from memory or SQLite, and writes one for an old log that has none) |
| `PageGivesUp` | `askDrive`: after 45 tries, "Lost touch with OpenTicker. Open this conversation again in a minute ..." |

Not modeled: what the agent writes, the work log, Stop's effect beyond closing the run, two questions in one conversation at once, the database failing a write.

## Findings on the current code

None open. Every rule holds.

Fixed: `EveryQuestionAnswered` used to break. `recover` marked a given-up run "error" before telling the conversation, so a stop between those two writes left the question without a reply for good. It now tells the conversation first, the order `_finish` uses; a stop in between leaves an open run whose log ends, which the next start closes through `_close_finished` without a second reply. `test_given_up_answer_told_once_across_a_stop` stops at each of the two writes and fails on the old order.

## Reading a result

Read every TLC result with the pstack `/statechart` skill: it turns a broken rule into its shortest path in plain words, and draws how a question moves between states when everything holds. The runner prints TLC's path as numbered steps with only the variables that changed, which is enough to start.

A broken rule is either a bug or a model that no longer matches the code. Before calling it a bug, replay the path on the real code, one action per step, using the map. The `Restart` tests show how: they write a run row and its events, call `runs.recover()`, and read the conversation. If the code doesn't do what the path says, fix the model.

## When you change the code on purpose

1. Change the code.
2. Change the matching actions in `TickAnswer.tla` so the map stays true, and the map table here.
3. If a rule should now be different, change the rule and say why in the commit. Never weaken a rule to make it pass.
4. Run the check. Add a test to `Restart` for any new restart step.
5. Move `synced` to the new commit only after you've read the covered code at that commit and confirmed the model describes it.

## How the check was shown to catch breaks

At 3218198 each rule was broken on purpose, and the check caught it:
- `OneAnswer`: `recover` resuming a run whose log already ends (the `_close_finished` branch removed). Model: `ComesBackResumes` from "ended" → `OneAnswer` breaks. Code: `test_finished_answer_not_answered_twice` fails.
- `PageEndsWithTheLog`: the page treating a dropped stream as the end. Model: `ShowEnd` without `srv \in LogEnds` → breaks.
- `EveryQuestionAnswered`: `recover` closing a given-up run before `chat_add` (the order before the fix). Model: `GiveUpTold` after the close → breaks. Code: `test_given_up_answer_told_once_across_a_stop` fails.
