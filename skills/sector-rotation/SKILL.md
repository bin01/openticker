---
name: sector-rotation
description: Which sectors and styles are leading or lagging the stock market, over days to months, and what the rotation suggests. Use for "which sectors are leading", "sector rotation", "where is money moving".
metadata:
  blurb: "Leaders and laggards across sectors, and what the shift says"
  label: "Which sectors lead?"
  scope: market
  order: 2
  prompt: "Which sectors are leading and lagging right now, and what does it say?"
---

# Sector rotation

Data: `openticker market`, which includes the sector funds over 1D, 1W, 1M and 3M, and `openticker fund SPY --h 1M` for the stocks behind the moves.

1. **Leaders and laggards**: the top three and bottom three sectors over 1 month, with 1-week and 3-month figures for context. Say whether leadership is new (1W against 3M) or established.
2. **The pattern**: name it plainly. Examples are risk-on (tech, discretionary, financials leading), defensive (utilities, staples, health care), or rate-driven (real estate and utilities following yields), and tie it to the macro numbers (10-year yield, dollar, oil).
3. **Who's doing the work**: the handful of large stocks behind the leading sector's move.
4. **What would confirm or break it** next.

Keep it under 220 words. Use a small table for the sector numbers.
