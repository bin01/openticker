---
name: week-ahead
description: Lays out what to watch in the coming week for the user's stocks and the market - earnings with implied moves, key economic releases and the backdrop going in - ordered by day. Use when the user asks what to watch this week, what's coming up, or about upcoming earnings and economic data.
metadata:
  blurb: "Earnings, economic data and setups, day by day"
  order: 2
  label: "What to watch this week"
  scope: portfolio
  prompt: "What should I watch this week?"
---

# Week ahead

**Data**: `openticker calendar` and `openticker market`. The user's stocks and their brief usually come with the question; if they don't, `openticker portfolio`. Share counts and dollar amounts aren't needed here.

## Cover

1. **Your stocks**: earnings this week (the day, before the open or after the close, the implied move), plus anything in the brief that sets up the week.
2. **Market movers**: the biggest companies reporting, and the key economic releases, such as inflation (CPI), jobs, the Fed or GDP, with a few words on why each matters.
3. **Going in**: one or two lines on rates, the dollar, oil and the VIX, and whether the market enters the week strong or weak.

## Answer shape

A list grouped by day (**Monday, Nov 9**, and so on), the user's stocks first within each day, then **Going in** at the end. Scannable, under 220 words.

## Before you send

- Every item has a real date from the data.
- Days with nothing important are left out rather than filled.
