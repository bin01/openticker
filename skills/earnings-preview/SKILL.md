---
name: earnings-preview
description: Walks through a company's earnings - before a report, the date, the bar to beat, how the stock usually reacts and the move options price in; after a report, the result against expectations, guidance and the reaction. Use when the user asks about earnings, an upcoming report, what to expect, whether a company beat, or how the stock reacted.
metadata:
  blurb: "Before a report: the bar and the implied move. After: what happened"
  order: 4
  label: "Earnings"
  scope: stock
  prompt: "Walk me through {t}'s earnings."
---

# Earnings

**Data**: `openticker earnings TICKER` and `openticker analysts TICKER`. Add `openticker financials TICKER` for revenue and margins.

## First, pick the mode

Compare the earnings date with today's date in the data.

- **Preview** when the next report is ahead.
- **Recap** when the last report was within the past 10 trading days. Search the web for the release and guidance if you can, because Yahoo's data has EPS but not guidance.
- Otherwise do a preview of the next report, and open with one line on how the last one went.

## Preview

1. **When**: the date and whether it's before the open or after the close, and how many days away.
2. **The bar**: the EPS and revenue estimates for the quarter, and how EPS estimates moved over 30 and 90 days. Estimates rising into a report raise the bar.
3. **Track record**: how often it beat, and the reactions. Point out when beats still led to drops, since that means a beat alone isn't enough.
4. **Implied move against history**: the ± move options price in, against the average past next-session move. If options price more than usual, the market expects a bigger surprise. If less, it may be complacent.
5. **What matters most this time**: the one or two things the market will judge, such as guidance, a key segment or margins. Base it on the business, the estimate trend and recent news, and say it's your read.

## Recap

1. **Result against expectations**: EPS and revenue against estimates, and growth from a year ago.
2. **Guidance**: raised, held or cut, if you found it.
3. **Reaction**: the next session and five sessions later, against the implied move and the usual reaction.
4. **What changed**: how analysts moved targets and estimates since the report.

## Answer shape

Lead with one line: the date and the bar for a preview, or "beat and fell" or "missed and rose" for a recap. Put the track record in a table of the last four to six reports: date, EPS against estimate, and the reaction. Keep it under 250 words.

## Before you send

- Dates are written out as dates, not "next week".
- The implied move and the past moves are compared, not just listed side by side.
- A guess about what matters is labeled as a guess.
