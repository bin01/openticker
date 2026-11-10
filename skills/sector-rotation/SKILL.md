---
name: sector-rotation
description: Shows which sectors are leading and lagging the stock market over days to months, names the pattern (risk-on, defensive, rate-driven) and the stocks behind it, and says what would confirm or break it. Use when the user asks which sectors are leading, about sector rotation, or where money is moving.
metadata:
  blurb: "Leaders and laggards across sectors, and what the shift says"
  order: 2
  label: "Which sectors lead?"
  scope: market
  prompt: "Which sectors are leading and lagging right now, and what does it say?"
---

# Sector rotation

**Data**: `openticker market` for the 11 sector funds over 1D, 1W, 1M and 3M, and `openticker fund SPY --h 1M` for the stocks behind the moves.

## Cover

1. **Leaders and laggards**: the top three and bottom three sectors over 1 month, with 1-week and 3-month figures. Leadership that shows in 1W but not 3M is new; leadership in both is established.
2. **The pattern**, named plainly and tied to the macro numbers:
   - Risk-on: tech, consumer discretionary and financials leading.
   - Defensive: utilities, consumer staples and health care leading.
   - Rate-driven: real estate and utilities moving with the 10-year yield.
3. **Who's doing the work**: the few large stocks behind the leading sector's move.
4. **What would confirm or break it** next.

## Answer shape

A small table of the leaders and laggards, then the pattern, the stocks behind it and what to watch, under 220 words.

## Before you send

- The pattern you name is supported by at least two sectors moving the same way.
- A rate-driven call cites the 10-year yield's 1M change from the Macro table, and the sectors move the way that change predicts (falling yields lift real estate and utilities).
- Every "new" or "established" label matches the 1W and 3M columns, and the confirm-or-break item is a level or a release with a date, not a general hope.
