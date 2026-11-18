---
name: industry-check
description: Explains what is driving a company's or a sector's business from the industry around it, the way a stock picker does due diligence. Covers who is buying and why, how the product's use is shifting, what limits supply, which customers and suppliers the story depends on and how they pay for it, where the cycle stands, what would break the story, and which of the user's own holdings sit on either side of it. Use when the user asks about industry trends, supply and demand, customers, suppliers or market share, whether a story or thesis still holds, what a company's business depends on, or wants a view that goes beyond the numbers.
metadata:
  blurb: "Demand, supply, customers, and what would break the story"
  order: 4
  label: "Industry check"
  scope: stock
  data: "financials"
  match: "industry|supply|demand|suppliers?|customers?|market share|moat|thesis|value chain|bottleneck|shortage|(story|trade|theme) .{0,20}(intact|hold|over|broken)|still intact|beyond the numbers|only (from|about|at|in) (the )?numbers"
  prompt: "What's driving {t}'s business? Walk me through demand, supply, its customers, and what would break the story."
---

# Industry check

A stock's numbers are the end of a chain: someone needs something, someone can only make so much of it, and money moves between them. This playbook reads that chain first, then checks it against the price.

**Data**:
- `openticker stock TICKER` and `openticker financials TICKER` (usually in the conversation already), and `openticker compare TICKER PEER1 PEER2` with its closest rivals.
- For a whole industry, `openticker market` for the sector funds and `openticker compare` on the three or four companies that show it best.
- The person's holdings come with the question as weights. That's enough here; exact shares and dollars aren't needed.
- The rest comes from reading: the company's latest earnings call and annual report, what its largest customers and suppliers said in theirs, and named industry researchers. Three or four good sources are enough; this is an hour's due diligence boiled down, not a research report. If you can't read the web, work from what you know, say so once, and give only figures you can date.

If the question is a lookup that happens to use one of these words ("who is its biggest customer?"), answer it in a few lines and stop. If it's about an industry and not one company ("chip stocks", "the banks"), run the same steps for the industry and name the companies that show each point.

## Work through

Choose the links that decide this business and spend the words there. Three links with evidence beat seven without.

1. **Demand**: who buys and what they use it for. Is the need growing, and is it shifting, from one kind of product to another or from a few early buyers to many? Use the buyers' own numbers: spending plans, orders, backlog, units.
2. **Supply**: what caps how much can be sold, and who controls it: a scarce part, factory capacity, lead times, power, a license. While supply is the limit, prices hold and the scarce link keeps the profit. When supply catches up, prices fall before volumes do. Say which state this industry is in, with a price or a lead time as evidence.
3. **Who the story depends on**: the few customers or suppliers that carry it (the annual report names them), what each is signalling, and whether they can walk away: switch supplier, build it themselves, or push the price down. A company that sells to everyone in a build-out is better placed than one tied to a single buyer.
4. **Where the money comes from**: how the buyers pay. Spending out of cash flow lasts; spending out of debt or investors' money stops when the funding does. Set the spending against the revenue it's meant to earn.
5. **Where the cycle stands**: early (shortages, rising prices), middle (capacity being added) or late (inventory building, prices slipping). Parts of one industry can sit at different points, so say which part this company is in.
6. **What would break it**: the one or two developments that would prove the story wrong, each tied to something checkable: a customer's order, a supplier's price, a date.
7. **Against the price**: one or two lines. Is this already what the market believes (estimates rising, a multiple at the top of its range), or is the price doubting it?
8. **Your portfolio**: which holdings ride the same trend and which sit on the other side of it. One company's revenue is another's cost, so say roughly what share of the portfolio is on each side.

## Answer shape

- Open with the view in two to four bold sentences: what is really driving the business, what is changing, and the weak spot. For example: "Demand hasn't cracked. What's changing is where the money goes inside the build-out, and that shift favors this company. Its weak spot is customers: the biggest one is spreading its orders."
- Then three or four short sections. Each heading states its conclusion, not just its topic ("Supply: sold out through next year", not "Supply"), so the answer can be read from the headings alone. Two to four bullets each, most with a number, its source and its date.
- Then **What breaks the story**, one short paragraph on the person's portfolio, and one line on what to watch, with dates.
- 350 to 500 words. Past that it stops being read, so cut the weakest section instead of trimming every line. Explain each industry term in a few words the first time it appears ("inference: running a trained model").

## Before you send

- Each section says something that could turn out wrong. "Demand is strong" fails; "orders for running models are growing twice as fast as orders for training them" passes.
- Every outside figure has a source and a date, and what's reported is kept apart from your own reasoning. A figure you couldn't source is left out, not softened to "about".
- The answer is a view of the business. It doesn't tell the person to buy or sell, and it doesn't forecast a price.
