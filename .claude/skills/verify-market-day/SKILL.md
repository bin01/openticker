---
name: verify-market-day
description: Model-checks one New York weekday of live prices (trading day, market holiday, or a closure the calendar doesn't know) so that a closed day never gets a row of prices or a close note, and the header and Market page say open or closed truthfully. Use when changing the stream or polling in app/server.py (on_stream_msg, apply_price, poll_loop, market_open, close_note_loop), the exchange calendar in app/yahoo_extra.py (market_holidays, session_hours, clock_status), or setStatus in app/index.html.
metadata:
  synced: 3218198
  covers: app/server.py app/yahoo_extra.py app/index.html
  models: TradingDay.cfg Holiday.cfg Closure.cfg
  known:
  tests: tests.test_state_machines.Calendar tests.test_state_machines.Holiday tests.test_invariants.MarketToday tests.test_invariants.HalfDays
---

# Verify a market day

Prices reach OpenTicker two ways during the day: Yahoo's stream, and a poll of one-minute bars when the stream goes quiet (app/server.py). A new row in `S.dates` means a new trading day, and the close note goes out for any day that has one. `MarketDay.tla` models one weekday from before the open to the evening, with the stream and Yahoo free to stop and come back, on three kinds of day: `TradingDay.cfg`, `Holiday.cfg` (Thanksgiving, which the calendar knows) and `Closure.cfg` (the exchange shut, the calendar saying open). The tests run `poll_loop` and `close_note_loop` once against a fake clock and fake bars.

## The rules

| Rule | In plain words | If it broke |
| --- | --- | --- |
| `NoPricesForAClosedDay` | A day the exchange didn't trade never gets a row of prices. | Every stock shows 0.0% for a day that didn't happen, charts get a flat extra day, and returns are off by a day. |
| `NoCloseNoteOnAClosedDay` | No close note for a day the exchange didn't trade. | A "market closed" notification on Thanksgiving. |
| `HeaderSaysClosedOnlyWhenClosed` | The header says "Market closed" only when it is. | During an outage the header says the market is closed when it's open and prices are just late. |
| `HeaderSaysPollingOnlyWhenOpen` | The header says "polling" only while the market is open. | The header claims live polling on a holiday. |
| `MarketChipIsRight` | The Market page's chip says open exactly when the market is open (for days the calendar knows). | "Open" on a holiday, or "Closed" mid-session. |

## Run it

```sh
python3 .claude/formal/verify.py market-day
```

About fifteen seconds. Needs Java 11 or later (`brew install openjdk`); downloads TLC once; uses `.venv` for the tests if present. Exits 0 when every rule holds and the tests pass. `server.py` and `index.html` are large and covered only in part, so the runner's "changed since" line is often noise: check whether the change touches a function in the map.

## Does your change touch this?

Yes if it changes any function in the map, what counts as the market being open, the five-minute grace after the close, `POLL_FALLBACK`, `poll_after`, how a row gets added to `S.dates`, or the holiday list.

## The map: model step to code

| Action / definition | Code |
| --- | --- |
| `Trades`, `CalendarOpen` | whether the exchange really trades; `yahoo_extra.session_hours(today)` is not None |
| `MarketOpens`, `StreamTicks` | `on_stream_msg` with `market_hours == 1` → `S.apply_price(sym, price, day)` with the trade's own New York date; a date past `S.dates[-1]` opens a row |
| `MarketCloses` | the clock passes the close plus five minutes (`market_open`) and the last poll goes stale (`setStatus` reads 180 s) |
| `StreamGoesQuiet` | no regular-hours tick for `POLL_FALLBACK` |
| `YahooStops`, `YahooBack` | Yahoo down or up for both stream and downloads |
| `Poll` | `poll_loop`: `market_open(now)` and quiet and not polled lately and past `S.poll_after` → `download_closes(period="1d", interval="1m")`; bars dated today are applied (a new row) and set `S.last_poll`; bars from another day set `poll_after = now + 600` and nothing else |
| `WaitEnds` | ten minutes pass |
| `CloseNote` | `close_note_loop`: `session_hours(today)`, 15 minutes past its close, `S.dates[-1] == today`, no `close|day` event yet |
| `Header` | `setStatus` in index.html: Live under 90 s since a tick; polling under 180 s since a poll; `L.open` → "Prices delayed" or "waiting"; else "Market closed" |
| `MarketChip` | `yahoo_extra.clock_status`, from the calendar alone |

Not modeled: pre-market and after-hours prices (`apply_ext`, `ext_poll`), the half-day 1 pm close (`session_hours` returns it; `tests.test_invariants.HalfDays` covers it), the history refresh, which symbols are stale, weekends (no loop acts on them), and anything past one day.

## Findings on the current code

None. Every rule holds on all three kinds of day. The first audit's bugs here (a phantom "today" on holidays, a close note on Thanksgiving, "Market closed" during a Yahoo outage, the chip saying open on holidays) were fixed in #3 and #19, and these rules keep them fixed.

On a closure the calendar doesn't know, the Market chip still says "open" and the header says "Market open · waiting for prices". That's the limit of a calendar; `MarketChipIsRight` excludes that day on purpose.

## Reading a result

Read every TLC result with the pstack `/statechart` skill: it shows a broken rule as its shortest path in plain words, and draws the day's states when everything holds. The runner prints TLC's path as numbered steps with only the variables that changed.

Before calling a broken rule a bug, replay its path on the real code one action per step. The `Holiday` tests show how: `clock()` fixes the time, `bars()` fakes the minute bars, `one_pass()` runs a loop body once.

## When you change the code on purpose

1. Change the code.
2. Change the matching action or definition in `MarketDay.tla` and the map here.
3. Change a rule only if the promise itself changed, and say why in the commit. Never weaken a rule to make it pass.
4. Run the check; add a test to `Holiday` or `Calendar` for any new path.
5. Move `synced` to the new commit only after reading the covered functions at that commit and confirming the model describes them.

## How the check was shown to catch breaks

At 3218198, with the `bar_day != day` check removed from `poll_loop` (the last session's bars filed under today), the check failed twice over: `test_unexpected_closure_bars_ignored` failed on the real code, and with the same change mirrored in `Poll`, the `Closure` config broke `NoPricesForAClosedDay`, `NoCloseNoteOnAClosedDay` and `HeaderSaysPollingOnlyWhenOpen`: the market opens, the stream stays quiet, the poll files yesterday's bars under today, and the close note goes out.
