---
name: valuation-check
description: Answers whether a stock is cheap or expensive by comparing its multiples (P/E, price/sales, PEG) with its growth, its own history and close peers, in plain words. Use when the user asks if a stock is expensive, overvalued or cheap, or about its valuation or P/E.
metadata:
  blurb: "Multiples against growth and peers, in plain words"
  order: 9
  label: "Is it expensive?"
  scope: stock
  prompt: "Is {t} expensive right now?"
---

# Is it expensive?

**Data**: `openticker stock TICKER`, then `openticker compare TICKER PEER1 PEER2 PEER3` with three close competitors.

## Work through

1. **The multiples in plain words**: trailing and forward P/E, price/sales and PEG. For example, "you pay $26 for each $1 of the last year's profit, and $13 for each $1 expected next year."
2. **Against growth**: whether the forward P/E is justified by expected EPS growth. A PEG near 1 is the usual rough line for "fairly priced for its growth".
3. **Against peers**: a small table of the same multiples and growth.
4. **What's priced in**: roughly what growth the price assumes, and what happens to the multiple if growth disappoints.

## Answer shape

Answer at the top: cheap, fair or expensive, and against what. Then the four points, under 220 words, with the peer table.

## Before you send

- Each multiple is explained in plain words the first time it appears.
- Peers are real competitors in the same business, not just the same sector.
