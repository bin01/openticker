---
name: bull-bear
description: Balanced bull case vs bear case for a stock, built from its numbers, with what would prove each side right. Use for "should I worry about TICKER", "bull and bear case", "what could go wrong".
metadata:
  blurb: "Both sides, each tied to a number, and what settles it"
  order: 3
  label: "Bull vs bear"
  scope: stock
  prompt: "Lay out the bull and bear case for {t}."
---

# Bull vs bear

Data: `openticker stock TICKER`, and also `openticker financials TICKER` for the growth and margin trend.

Format:
- **The bull case**: three points, each tied to a number, such as growth rate, margin trend, rising estimates, target upside or insider buying.
- **The bear case**: three points, each tied to a number, such as valuation against growth, slowing revenue, estimate cuts, heavy insider selling, crowded positioning or a broken trend.
- **What decides it**: the one or two things to watch that would settle the debate, with dates where possible (next earnings, guidance).
- **Where the market sits**: whether the price and consensus already lean bull or bear.

Be fair to both sides. Do not end with a recommendation to buy or sell.
