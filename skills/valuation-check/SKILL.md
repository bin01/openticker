---
name: valuation-check
description: Is a stock cheap or expensive? Compares its multiples with its growth, its history and peers. Use for "is TICKER expensive", "valuation".
metadata:
  blurb: "Multiples against growth and peers, in plain words"
  order: 6
  label: "Is it expensive?"
  scope: stock
  prompt: "Is {t} expensive right now?"
---

# Valuation check

Data: `openticker stock TICKER`. For peers, use `openticker compare TICKER PEER1 PEER2 PEER3` with three close competitors.

1. The headline multiples: trailing and forward P/E, price/sales and PEG, explained in plain words. For example, "you pay $X for each $1 of next year's expected profit."
2. Growth-adjusted: is the forward P/E justified by the expected EPS growth?
3. Against peers: use a small table.
4. What's priced in: the growth the current price implies, roughly, and what happens if growth disappoints.

Answer the question directly at the top: cheap, fair or expensive, and relative to what.
