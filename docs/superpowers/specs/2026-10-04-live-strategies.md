# Live trading: what each strategy does on a trading day

October 4, 2026. Companion to
[2026-10-04-strategy-research.md](2026-10-04-strategy-research.md). That doc ranks strategies;
this one says how each runs live: where every input comes from, how the system learns that new
data exists, when it decides, and what orders it sends.

![Live trading day: EDGAR and Alpaca feed a point-in-time store through a filing watcher and a
price snapshot; a 15:30 decision run computes targets, a 15:40 order run sends them to Alpaca,
and a 16:15 reconcile compares fills with the backtest](2026-10-04-live-day.png)

Diagram source: [`2026-10-04-live-day.html`](2026-10-04-live-day.html).

## The rule

A strategy is only allowed in if:

1. every input has a live source that delivers before the decision time,
2. the system can discover new data on its own (no one pasting files in),
3. every order it emits is one Alpaca accepts, and
4. the backtest reads the same data at the same moment the live run would.

Point 4 is what keeps the backtest honest. The strategy is one function,
`decide(as_of, data) -> {symbol: weight}`. Every data query takes `as_of` and returns only rows
the system would have had at that moment (prices up to then, filings with an acceptance time
before then). A backtest calls it with past `as_of` values; the live run calls it with now.
There is no separate live version of the strategy to drift out of sync.

## Facts this design rests on

Each was checked on 2026-10-04.

- **Alpaca order rules** ([docs](https://docs.alpaca.markets/docs/orders-at-alpaca)):
  market-on-close (`cls`) orders are rejected after 15:50 ET; market-on-open (`opg`) after 09:28.
  Fractional orders accept only `day` time in force, so a fractional rebalance cannot use the
  closing auction. Notional (dollar-amount) orders are supported but cannot be replaced, only
  cancelled and resent.
- **Alpaca market data, free plan**: real-time prices from IEX only; consolidated SIP bars are
  15 minutes delayed (btest's ingest already respects this, `SIP_DELAY` in
  `sources/alpaca.py`).
- **SEC update speed** ([EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)):
  the submissions API updates "with a typical processing delay of less than a second", the XBRL
  APIs "under a minute". Bulk zips rebuild nightly at about 03:00 ET.
- **EDGAR latest-filings feed**:
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-Q&count=100&output=atom`
  returns the newest filings of a form type with company name, CIK and timestamp (tested with
  `10-Q` and `4`).
- **EDGAR daily index** ([accessing EDGAR data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)):
  `Archives/edgar/daily-index/YYYY/QTRn/form.YYYYMMDD.idx`, built nightly from about 22:00 ET.
  Filings after 17:30 can land in the next day's index. Limit 10 requests a second, with a
  User-Agent naming a contact address.
- **Ticker to CIK map**: `https://www.sec.gov/files/company_tickers.json` (10,440 companies).
- **Alpaca options** ([docs](https://docs.alpaca.markets/docs/options-trading)): level 1 allows
  cash-secured puts. In-the-money contracts auto-exercise at expiry. Assignments do not arrive
  on the websocket and must be polled from the REST activities endpoint; on paper accounts they
  appear there only the next day.

## The live day (times ET)

Early-close days (13:00 close, already in `market.session.close_utc`) shift every intraday step
back by three hours.

| Time | Job | What it does |
|---|---|---|
| Weekly, Sunday | Universe refresh | Download current index members (S&P 500 from the SPY fund's published holdings), map tickers to CIKs with `company_tickers.json`, record joins and leaves with dates. Alarm on any ticker with no CIK. |
| Every 10 min, 06:00-20:00 | Filing watcher | Read the latest-filings feed for `10-Q`, `10-K`, `8-K` and `4`. Keep entries whose CIK is in the universe and whose accession number is new. For each, fetch what the strategy needs (below) and append it with the filing's acceptance time. |
| 15:30 | Price snapshot | Pull SIP minute bars through the latest available minute (about 15:14, because of the 15-minute delay) for the universe and append them. |
| 15:30 | Decision run | For each strategy scheduled today, call `decide(now, data)`, save the target weights. |
| 15:40 | Order run | Read Alpaca positions, diff against targets, send sells as `day` market orders, wait for fills (up to 5 minutes), then send buys sized from the cash actually received. Every order gets a `client_order_id` of `strategy:date:symbol:leg`, so a retried run cannot double-order. |
| 16:15 | Reconcile | Read fills and positions from Alpaca, store them, and compare with what the backtest fill model says should have happened today. Alarm if they differ by more than a set tolerance. |
| 18:00 | Price ingest | Existing nightly ingest (22:00 UTC) fills the day's full minute bars. |
| ~01:00 | Filing reconcile | Read yesterday's `form.YYYYMMDD.idx` and fetch any universe filing the watcher missed. A miss is logged, since it means the intraday feed lagged. |

The backtest copies this timing: decide on data through the 15:14 bar, fill at the 15:45 bar's
open plus the spread cost. That replaces today's "fill at the next bar's open", which for daily
bars means tomorrow morning, a different trade from the one the live system makes.

Market-on-close and market-on-open orders are not used (user decision, 2026-10-04). Every
strategy trades with fractional `day` market orders in the 15:40 run, so backtest and live share
one fill rule.

## Worked example: multi-factor stocks from SEC financials (#3)

**Inputs.** For each S&P 500 company: gross profit, total assets, stockholders' equity, shares
outstanding (from SEC companyfacts), daily closes (from Alpaca).

**How it finds new filings.** The filing watcher sees a `10-Q` or `10-K` from a universe CIK in
the feed, then calls `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` for that company.
Every fact in that response carries its accession number and `filed` date. Rows whose accession
number matches the new filing are appended to `fundamentals.fact`
`(cik, concept, period_end, value, accession, accepted_at)`. Nothing is overwritten: a
restatement arrives as a new row with a later `accepted_at`, so a backtest at an earlier
`as_of` still sees the original number. The 01:00 reconcile against the daily index catches
filings the feed missed.

**How it knows which numbers to read.** Companies tag the same line differently (revenue alone
appears as `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`,
`SalesRevenueNet` and others). A table `fundamentals.concept_map` lists, per field, the tags to
try in order. After each 10-Q the job checks every field resolved; a company with a missing
field is excluded from ranking and listed on the run page, never silently scored as zero.

**The decision.** Last trading day of each month at 15:30:

1. For each company, take the latest value of each field with `accepted_at < now`.
2. Gross profitability = gross profit / total assets. Value = book equity / market cap (shares x
   the 15:14 price). Momentum = return from 12 months ago to 1 month ago.
3. Turn each into a cross-sectional z-score, average them, take the top 25.
4. Target weight 4% each; fractional shares make $800 positions exact at $20k.

**Orders.** The 15:40 order run sells names that dropped out, then buys new names and tops up
the rest, all as fractional `day` market orders.

**When something breaks.**

- SEC unreachable: decide on the last stored values. Fundamentals change quarterly, so one
  missed day changes nothing; alarm if the outage passes a day.
- Alpaca price snapshot fails: skip the rebalance and retry at 15:30 the next trading day.
- Order run dies between sells and buys: the next run diffs actual positions against the same
  targets and sends only what is missing (the `client_order_id` stops repeats).

## Every strategy, live

Numbers match the research doc's ranking.

| # | Strategy | Inputs, live source | How new data is found | Decides | Orders | Live caveats |
|---|---|---|---|---|---|---|
| 1 | Multi-asset trend | ETF closes, Alpaca | 15:30 snapshot | Last trading day of month, 15:30 | Fractional `day` market, sells first | None beyond the shared jobs |
| 2 | Stock momentum | Stock closes, Alpaca; index members, SPY holdings | Snapshot; weekly universe refresh | Monthly, 15:30 | As #1 | A stock leaving the index is sold at the next rebalance, not the day it leaves (state this in the backtest too) |
| 3 | Multi-factor | SEC companyfacts + Alpaca | Filing watcher on `10-Q`/`10-K` | Monthly, 15:30 | As #1 | Concept mapping needs upkeep; the coverage check flags gaps |
| 4 | Post-earnings drift | Earnings per share: SEC companyfacts (from the 10-Q) | Filing watcher on `10-Q`/`10-K` | Daily, 15:30, for filings accepted since yesterday's run | Buy on signal, sell after 60 trading days | Uses the 10-Q date, which comes days to weeks after the earnings release. The faster version reads EPS from the 8-K press release text, which is untagged and needs an extractor; it may only go live if the backtest runs the same extractor over past press releases. Start with the 10-Q version. |
| 5 | Put writing | SPY option chain and quotes, Alpaca | 15:30 options snapshot | Expiry day, or the day after an assignment | Sell one cash-secured put about 30 days out (level 1) | Assignment must be polled from REST activities (no websocket; next-day on paper). If assigned, sell the shares at the next 15:40 run. Backtest data starts February 2024, so the backtest is short. |
| 6 | Insider buying | Form 4 XML from EDGAR | Filing watcher on `4`; parse transaction code `P`, price, shares, insider's role | Daily, 15:30, over filings in the last 30 days | Buy on a cluster signal, hold a fixed period | Form 4 is due within two business days of the trade, so the signal is at least that stale; the backtest uses the filing time, not the trade date. Backtest data comes from SEC's quarterly data sets; check once that the live XML parser and the data sets agree on the same quarter. |
| 7 | ETF relative momentum | ETF closes, Alpaca | Snapshot | Monthly, 15:30 | As #1 | None |
| 8 | Short-term mean reversion | ETF closes, Alpaca | Snapshot | Daily, 15:30 | As #1 | Daily trading makes the backtest's spread cost decisive |
| 9 | Calendar effects | NYSE calendar (have it); FOMC dates from the Fed's calendar | FOMC dates typed in yearly; alarm when no future meeting is stored | Scheduled days, 15:30 | As #1 | Pre-FOMC hold enters the afternoon before the announcement day |
| 10 | Vol targeting overlay | Closes of whatever it scales, Alpaca | Snapshot | With the strategy it wraps | Scales that strategy's targets | None |

All ten pass the rule. #4 and #5 carry the most live work: #4 because the fast signal needs text
extraction, #5 because options add assignment handling and a short backtest.

## Fit with the strategy lab

Strategies stay what they are today: one Python file with one `Strategy` subclass, edited,
versioned, duplicated and run from the website's Strategies tab or from `strategies/` with the
CLI. The new data sources change what a strategy can read, not how it is written or run.

- **Strategy code never fetches data.** The worker's data jobs (filing watcher, price
  snapshot, universe refresh) write to Postgres. Lab jobs already run in a child process with
  secrets stripped (`child_env` in `worker.py`) as the `btest_runner` role, which has `SELECT`
  on the `market` schema. New tables go in `market` (or a new schema added to `grant_runner`),
  so a strategy reads SEC financials the same way it reads splits today.
- **One new hook, same file shape.** `decide(as_of, data)` joins `on_bar` and `signals` as an
  optional method on the subclass. Existing `on_bar` strategies keep working unchanged. The
  strategy template (`templates/strategy_template.py`) documents the new hook and the `data`
  calls (`universe`, `daily_closes`, `fundamentals`, `insider_trades`, `report`).
- **Params stay editable and sweepable.** `holdings`, `skip_days` and the rest sit in `params`
  like any strategy today; changing one in the editor and pressing Cmd/Ctrl+Enter reruns it.
  Sweeps need the portfolio fast path (G9) or fall back to the event engine.
- **The run form gains a universe option.** Today a run takes a symbol list from `btest.toml`.
  A `decide` strategy declares `universe = "sp500"` (or an ETF list); the form shows it instead
  of the symbol box.
- **Live uses the same saved version.** Going live means pointing the scheduler at a lab
  strategy version (`lab.strategy` row), so the code that trades is the exact version that was
  backtested. Editing the strategy makes a new version; the live job keeps the old one until it
  is switched over.

## What btest needs for live

These sit next to the backtesting gaps (G1 to G14) in the research doc.

| ID | Piece | Purpose |
|---|---|---|
| L1 | Point-in-time data access | Every query takes `as_of`; filings stored with `accepted_at`, append-only. One code path for backtest and live. |
| L2 | Live data jobs | Universe refresh, filing watcher (feed plus nightly index reconcile), companyfacts fetch, Form 4 parser, 15:30 price and options snapshots. |
| L3 | Scheduler | Runs jobs by NYSE session times from `market.session`, including early closes. Lives on the worker, which already runs the nightly ingest. |
| L4 | Broker adapter | Alpaca orders: sells before buys, notional or fractional `day` orders, `client_order_id` for idempotency, options orders and assignment polling. |
| L5 | Reconcile and safety | Store live fills; compare with the backtest fill model each day; a kill switch on daily loss and on order size; alarms to the user. |
| L6 | Fill model to match live | Backtest decision on data through 15:14, fill at the 15:45 open. |

Order: L1 and L6 first, because they change how backtests run and every result before them
uses a fill rule the live system cannot reproduce. Then L3, L4 and L5 on Alpaca paper trading
with #1 (prices only). L2's filing jobs come with the first SEC-based strategy.
