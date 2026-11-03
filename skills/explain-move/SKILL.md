---
name: explain-move
description: Explains why a stock moved today or over a period, separating the market, its sector and stock-specific news. Use for "why is TICKER up/down", "what happened to TICKER".
metadata:
  blurb: "Market, sector or company news? Sized against a normal day"
  order: 2
  label: "Why is it moving?"
  scope: stock
  prompt: "Why is {t} moving?"
---

# Explain a move

Data: `openticker stock TICKER`, then `openticker market` for the backdrop. If the reason isn't in the news data and you can search the web, search "TICKER stock today".

Break the move into three layers:
1. **Market**: what SPY and QQQ did over the same period. If the stock moved with them, say so plainly.
2. **Group**: whether peers or the sector moved the same way. Use `openticker compare TICKER PEER1 PEER2` with two or three obvious peers.
3. **Stock-specific**: news, an earnings report, rating or target changes, insider trades or unusual options in the window.

Size the move. Compare it with the stock's typical daily move ("a 3-sigma day" or "an ordinary wiggle").

Finish with whether the reason looks durable, such as changed estimates or guidance, or temporary, such as a flow, a sympathy move or a macro day. Never invent a reason. If nothing explains it, say the move has no clear catalyst in the data.
