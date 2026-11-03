---
name: earnings-preview
description: Preview of a company's upcoming earnings - date, what's expected, how the stock usually reacts, and what options are pricing. Use for "earnings preview", "what to expect from TICKER earnings".
metadata:
  blurb: "Date, the bar to beat, past reactions, the implied move"
  order: 4
  label: "Earnings preview"
  scope: stock
  prompt: "Preview {t}'s next earnings."
---

# Earnings preview

Data: `openticker earnings TICKER` and `openticker analysts TICKER`.

Cover:
1. **When**: the date, and whether it's before the open or after the close.
2. **The bar**: the EPS and revenue estimates for the quarter, and how much expectations moved over 30 and 90 days. Rising estimates into a print mean the bar is higher.
3. **Track record**: beats or misses over the last four to six quarters, and how the stock reacted the next session. Point out when beats still led to drops.
4. **Implied move**: what options price as ±%, compared with the typical past reaction.
5. **What matters most** this time, such as guidance or a key segment, based on the business and recent news.

If the earnings date has passed, write a recap: the result against expectations and the reaction.
