# Plan: from backtests to live trading for the ranked strategies

October 4, 2026. Merges the work orders in
[strategy research](../specs/2026-10-04-strategy-research.md) (gaps G1-G14) and
[live strategies](../specs/2026-10-04-live-strategies.md) (pieces L1-L6) into one sequence.
Architecture diagrams: [backtest gaps](../specs/2026-10-04-strategy-gaps.html),
[live day](../specs/2026-10-04-live-day.html).

Each step ends with something runnable from the strategy lab. Strategies stay editable Python
files throughout.

| Step | Work | Gaps | Done when |
|---|---|---|---|
| 1 | Point-in-time `data` object and the `decide(as_of, data)` hook; backtest fill at 15:45 after a 15:30 decision on data through 15:14 | L1, L6, G2, G3 | An existing daily strategy rewritten with `decide` gives the same targets as its `on_bar` version, and fills land at 15:45 |
| 2 | ETF universe (~25 tickers) ingested; fractional shares; T-bill yield on idle cash; 60/40 benchmark; run form universe option | G1, G4, G5 | Multi-asset trend (#1) backtests 2016-2024 from the lab |
| 3 | Remaining ETF strategies as lab files | | #7, #8, #9 (turn of month), #10 backtested |
| 4 | Scheduler, Alpaca broker adapter, reconcile and kill switch, on Alpaca paper | L3, L4, L5 | #1 trades on paper for a month; daily reconcile matches the backtest fill model |
| 5 | Stock universe: S&P 500 membership by date (free GitHub list), ticker-to-CIK map, daily stock bars from Alpaca including delisted; ticker-reuse check | G11 | Stock momentum (#2) backtests 2016-2024 without survivorship bias |
| 6 | SEC financials: companyfacts loader with filing times, concept map and coverage check, filing watcher and nightly index reconcile | G12, L2 | Multi-factor (#3) backtests; the watcher picks up a real 10-Q within 10 minutes |
| 7 | Event data: earnings filings, Form 4 parser checked against SEC's quarterly data sets, FOMC dates; per-symbol spread costs | G13, G8 | #4 (10-Q version), #6 and #9 (FOMC) backtest with realistic small-cap costs |
| 8 | Portfolio fast path, walk-forward, deflated Sharpe | G9, G10 | Sweeps over #1-#3 run on the fast path; each sweep reports walk-forward and deflated Sharpe |
| 9 | Options, only if chosen | G14 | Put writing (#5) backtests on Alpaca options data from 2024 |

Step 8 can start once step 1 fixes the portfolio rules, and run alongside steps 3-7. Any
strategy that passes its holdout check can move to paper trading from step 4 on; the holdout
(2025 onward) is spent by the user, not by the agent.

## Open decisions

1. Is 2016-2024 enough history for the stock strategies? If not, a paid source (Norgate $630 a
   year, or Sharadar) adds 1998-2015. Needed before step 5.
2. Are options in scope? Needed before step 9.
3. Margin or cash account? A cash account rules out shorting, which only the lower-ranked
   strategies need. Needed before step 4 goes live with real money.
