---- MODULE MarketDay ----
\* One weekday in New York, from before the open to the evening: the stream (on_stream_msg -> S.apply_price), the
\* polling fallback (poll_loop), the close note (close_note_loop), the exchange calendar (yahoo_extra.session_hours,
\* server.market_open, yahoo_extra.clock_status) and the header (setStatus in index.html). SKILL.md has the full map.

CONSTANT Day    \* "trading": a normal session
                \* "holiday": a market holiday the calendar knows (Thanksgiving, Good Friday)
                \* "closure": the exchange is shut but the calendar says open (a national day of mourning)

VARIABLES
    clock,      \* "before" the open, "open" (regular hours plus the five-minute grace), "evening" (15+ minutes after the close)
    stream,     \* "ticking": regular-hours trades arriving (S.last_tick under 60 s old); "silent"
    yahoo,      \* Yahoo answers
    polled,     \* S.last_poll is under three minutes old
    pollWait,   \* S.poll_after is in the future: the last poll's minute bars weren't today's
    row,        \* the newest row in S.dates: "yesterday" or "today"
    note        \* the close note for today went out

vars == <<clock, stream, yahoo, polled, pollWait, row, note>>

Trades == Day = "trading"                        \* the exchange really trades today
CalendarOpen == Day \in {"trading", "closure"}   \* session_hours(today) is not None

Init == clock = "before" /\ stream = "silent" /\ yahoo = TRUE /\ polled = FALSE /\ pollWait = FALSE
    /\ row = "yesterday" /\ note = FALSE

\* 9:30: on a trading day the first regular-hours trade streams in within seconds; apply_price opens today's row
MarketOpens == clock = "before" /\ clock' = "open"
    /\ (IF Trades /\ yahoo THEN stream' = "ticking" /\ row' = "today" ELSE UNCHANGED <<stream, row>>)
    /\ UNCHANGED <<yahoo, polled, pollWait, note>>

\* after the close (and 15 minutes): the stream stops and the last poll goes stale
MarketCloses == clock = "open" /\ clock' = "evening" /\ stream' = "silent" /\ polled' = FALSE
    /\ UNCHANGED <<yahoo, pollWait, row, note>>

\* on_stream_msg with market_hours == 1: the trade's own date picks the row, so only a real session opens one
StreamTicks == Trades /\ clock = "open" /\ stream = "silent" /\ yahoo
    /\ stream' = "ticking" /\ row' = "today" /\ UNCHANGED <<clock, yahoo, polled, pollWait, note>>
StreamGoesQuiet == stream = "ticking" /\ stream' = "silent" /\ UNCHANGED <<clock, yahoo, polled, pollWait, row, note>>

YahooStops == yahoo /\ yahoo' = FALSE /\ stream' = "silent" /\ polled' = FALSE
    /\ UNCHANGED <<clock, pollWait, row, note>>
YahooBack == ~yahoo /\ yahoo' = TRUE /\ UNCHANGED <<clock, stream, polled, pollWait, row, note>>

\* ten minutes after a poll that found the wrong day's bars
WaitEnds == pollWait /\ pollWait' = FALSE /\ UNCHANGED <<clock, stream, yahoo, polled, row, note>>

\* poll_loop: market_open() and the stream quiet for POLL_FALLBACK, not polled lately, not waiting.
\* download_closes(period="1d", interval="1m") returns the latest session's bars: today's if the exchange traded,
\* the last session's if it didn't. Only bars dated today are applied; otherwise poll_after = now + 600.
Poll == CalendarOpen /\ clock = "open" /\ stream = "silent" /\ yahoo /\ ~polled /\ ~pollWait
    /\ (IF Trades
        THEN polled' = TRUE /\ row' = "today" /\ UNCHANGED pollWait
        ELSE pollWait' = TRUE /\ UNCHANGED <<polled, row>>)
    /\ UNCHANGED <<clock, stream, yahoo, note>>

\* close_note_loop: session_hours(today) and 15 minutes past its close, S.dates[-1] == today, not sent yet
CloseNote == CalendarOpen /\ clock = "evening" /\ row = "today" /\ ~note
    /\ note' = TRUE /\ UNCHANGED <<clock, stream, yahoo, polled, pollWait, row>>

EndOfDay == clock = "evening" /\ UNCHANGED vars

Next == MarketOpens \/ MarketCloses \/ StreamTicks \/ StreamGoesQuiet \/ YahooStops \/ YahooBack \/ WaitEnds
    \/ Poll \/ CloseNote \/ EndOfDay

Spec == Init /\ [][Next]_vars

\* setStatus: lastTick under 90 s -> Live; lastPoll under 180 s -> polling; L.open (market_open) -> delayed/waiting;
\* otherwise "Market closed"
Header == IF stream = "ticking" THEN "live"
          ELSE IF polled THEN "polling"
          ELSE IF CalendarOpen /\ clock = "open" THEN "delayed"
          ELSE "closed"
\* the Market page chip: clock_status follows the calendar, whether or not Yahoo answers
MarketChip == IF CalendarOpen /\ clock = "open" THEN "open" ELSE "closed"

\* ---- Rules

\* A day the exchange didn't trade never gets a row of prices (which would show every stock at 0.0%).
NoPricesForAClosedDay == ~Trades => row = "yesterday"

\* No close note goes out for a day the exchange didn't trade.
NoCloseNoteOnAClosedDay == note => Trades

\* The header says "Market closed" only when the market is closed.
HeaderSaysClosedOnlyWhenClosed == Header = "closed" => ~(Trades /\ clock = "open")

\* The header says "polling" only while the market is open.
HeaderSaysPollingOnlyWhenOpen == Header = "polling" => (Trades /\ clock = "open")

\* The Market page says "open" exactly when the market is open (a closure the calendar doesn't know is out of reach).
MarketChipIsRight == Day # "closure" => (MarketChip = "open" <=> (Trades /\ clock = "open"))

====
