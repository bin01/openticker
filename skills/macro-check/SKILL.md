---
name: macro-check
description: Reads the macro backdrop for stocks - interest rates, the dollar, oil, gold, bitcoin and volatility (VIX) - and what it means for equities. Use for "what are rates doing", "macro backdrop", "is the market scared".
metadata:
  blurb: "Rates, dollar, oil and the VIX, and what they mean for stocks"
  label: "Macro backdrop"
  scope: market
  order: 3
  prompt: "What's the macro backdrop telling us about stocks right now?"
---

# Macro check

Data: `openticker market`.

1. **Rates**: the 10-year, 5-year and 3-month yields, their levels and their change over the day and the month. Rising long yields pressure richly valued growth stocks. A falling short rate hints at expected Fed cuts.
2. **Dollar, oil and gold**: what each did, and the usual read. A strong dollar weighs on multinationals. Oil feeds inflation and energy stocks. Gold reflects a hedging bid.
3. **Fear gauge**: the VIX level (below 15 is calm, above 25 is stressed) and its change.
4. **Net read for stocks**: one paragraph on whether the backdrop is a tailwind or a headwind, and the one release or level to watch (use `openticker calendar` for dates).

Under 220 words. Explain each term in a few words the first time it appears.
