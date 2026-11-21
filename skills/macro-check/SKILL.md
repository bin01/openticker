---
name: macro-check
description: Reads the macro backdrop for stocks - interest rates, the dollar, oil, gold, bitcoin and the VIX - says what each means for stocks, and nets it into a tailwind or headwind. Use when the user asks about rates, the macro backdrop, the Fed, inflation, the VIX, or whether the market is scared.
metadata:
  blurb: "Rates, dollar, oil and the VIX, and what they mean for stocks"
  order: 3
  label: "Macro backdrop"
  scope: market
  prompt: "What's the macro backdrop telling us about stocks right now?"
---

# Macro backdrop

**Data**: `openticker market`, and `openticker calendar` for upcoming releases.

## Cover

1. **Rates**: the 10-year, 5-year and 3-month yields, their level and their change over the day and the month. Rising long yields weigh on expensive growth stocks; a falling 3-month yield hints the market expects Fed cuts.
2. **Dollar, oil, gold and bitcoin**: what each did (all four are in the Macro table), and the usual read. A strong dollar hurts companies that sell abroad; oil feeds inflation and drives energy stocks; rising gold means investors want a hedge; bitcoin tends to track the appetite for risk, so a sharp drop alongside falling tech stocks says speculation is being pulled back.
3. **Fear and stress**: the VIX level and its change, and the "Under the hood" gauges (credit, breadth, risk appetite, fear, hedge funds) with their calm, watch or stressed reading. Use those readings rather than your own thresholds, so you and the Market page agree. Credit is the one to lead with: if bonds are calm while stocks are stressed, the selloff hasn't spread.
4. **Net read**: a tailwind or a headwind for stocks, and the one release or level to watch next, with its date.

## Answer shape

Open with the net read in one line, then the three parts, under 220 words.

## Before you send

- Each term (yield, VIX, basis point) is explained in a few words the first time it appears.
- The net read follows from the numbers given, not from a general view.
