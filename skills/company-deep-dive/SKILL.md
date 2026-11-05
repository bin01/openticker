---
name: company-deep-dive
description: Explains a company as an analyst would. Covers what it sells and to whom, which end markets its revenue comes from and where customers there are spending, its biggest customers, its growth drivers and limits, and what growth today's price assumes (worked back from the price in code) against analyst expectations and peers. Ends with whether the business can deliver what the price needs. Use when the user wants to understand a company, asks for a deep dive or the investment case, asks what's priced in or what growth the market expects, or asks where a company's growth comes from.
metadata:
  blurb: "The business, where its growth comes from, and what the price assumes"
  order: 2
  label: "Deep dive"
  scope: stock
  match: "priced in|deep dive|investment case|growth (driver|engine)|where .{0,30}growth|what (growth|is the market|does the market|are investors).{0,40}(assum|expect|pric|bet)|implied growth|reverse dcf"
  prompt: "Give me a deep dive on {t}: the business, where its growth comes from, and what today's price assumes."
---

# Deep dive

**Data**:
- `openticker stock TICKER`, `openticker financials TICKER`, `openticker analysts TICKER` and `openticker earnings TICKER`.
- `openticker compare TICKER PEER1 PEER2 PEER3`, with three close competitors.
- The latest 10-K or 20-F and the last two earnings calls or releases, from the SEC or the company's investor site. Use them for revenue by segment and end market, the largest customers and the outlook. SEC EDGAR refuses fetchers that don't say who they are: in the workbench use `ot.get` or `ot.get_json`; otherwise go to the company's investor site.
- For the biggest customers or end markets, their own latest capex plans or forecasts.

If the person asks only one part (for example only what's priced in), do that part in full and touch the rest in a line or two. The company is the one in view, or the one the conversation is about. If the question is about the market as a whole, not a company, set this playbook aside.

## Work through

1. **The business in a paragraph.** What it sells, to whom, how it makes money, and the segments with each one's share of revenue and profit.
2. **Follow the money: end markets.** Give revenue by end market (for example industrial, auto, data center, consumer) with shares. For the two or three biggest, say where customers' spending is heading now: capex plans, unit forecasts, inventory cycles. Give a number and a date for each. This decides whether growth comes, so spend the most effort here.
3. **Customers.** Cover concentration: the largest customers, or the share sold through distributors, from the 10-K. Then what those customers are signalling, and any shift: design wins or losses, customers making the part themselves, exposure to China or tariffs.
4. **Growth drivers and limits.** Cover new products, capacity and utilization, pricing power, margins and the capex cycle. Say which drivers are working and which are stalled.
5. **What the price assumes.** Do this in code in your workbench, never in your head:
   - Start from trailing free cash flow, or earnings if free cash flow is distorted by a capex cycle (say which, and why).
   - Discount at the 10-year Treasury yield plus beta times a 5% equity premium, and state the rate.
   - Run 10 years of growth, then 3% terminal growth, and solve for the growth that makes the value equal today's price.
   - Show how the answer moves with the discount rate one point either side, and with a 15× or 25× exit multiple instead of terminal growth.
   - Set the result against the analysts' consensus for next year and the long term, the company's guidance, its 5- and 10-year record, and what peers' multiples imply.
6. **The verdict.** Can the drivers in 2–4 deliver the growth in 5? What would close or widen the gap?

## Answer shape

Lead with two lines: what the company is in plain words, then the verdict. For example: "At $X, the price needs about N% a year of free cash flow growth for a decade. Its end markets point to M%, so the price leans on a margin recovery that hasn't started yet."

Then use short sections in the order above:
- end markets as a table (end market, share of revenue, direction, evidence);
- customers;
- drivers and limits;
- what's priced in, with a small sensitivity table;
- one line on what to watch, with dates.

Keep it to 450–650 words. A deep dive earns the length, but every line should carry a number or a judgment. Link each source inline the first time it's used. A bar chart of growth needed against consensus and history helps.

## Before you send

- The end-market and customer sections have numbers, dates and sources, not generic descriptions of the industry. Say when a figure is your estimate rather than reported.
- Every input of the price math is stated, and the numbers came from code you ran.
- Like is compared with like: free cash flow growth against free cash flow growth, not against revenue growth. If you have to bridge between them, say so.
