---
name: explain-move
description: Explains why a stock moved, today or over a period, by separating the market, its sector and peers, and stock-specific news, and by sizing the move against a normal day. Use when the user asks why a stock is up or down, what happened to it, or whether a move is unusual.
metadata:
  blurb: "Market, sector or company news? Sized against a normal day"
  order: 2
  label: "Why is it moving?"
  scope: stock
  prompt: "Why is {t} moving?"
---

# Why is it moving?

**Data**: `openticker stock TICKER`, then `openticker market` for the backdrop, and `openticker compare TICKER PEER1 PEER2` with two or three obvious peers. If you can search the web and the data doesn't explain it, search for the stock's news today.

## Break the move into three layers

1. **Market**: what SPY and QQQ did over the same period. If the stock moved in line with them, say so plainly.
2. **Group**: whether peers and the sector moved the same way. A move shared by the group is about the industry, not the company.
3. **Company**: news, an earnings report, rating or target changes, insider trades or unusual options in the window.

Then **size it**: compare the move with the stock's typical daily move from the data. About 1× is an ordinary day; 2× is notable; 3× or more is a real event.

## Answer shape

Open with the answer: "Mostly the market", "Chip stocks fell together", or "Company news: guidance cut". Then one line per layer with its number, and the size. Finish with whether the cause looks lasting (estimates, guidance, a change in the business) or passing (a flow, a sympathy move, a macro day). Under 180 words.

## Before you send

- Never invent a reason. If nothing in the data or the news explains the move, say there's no clear catalyst.
- The period you explain matches the period the user asked about.
