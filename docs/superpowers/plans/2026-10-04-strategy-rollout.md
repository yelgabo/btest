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
| 9 | Options data and engine (in scope) | G14 | Put writing (#5) backtests on Alpaca options data from 2024 |

Step 8 can start once step 1 fixes the portfolio rules, and run alongside steps 3-7. Any
strategy that passes its holdout check can move to paper trading from step 4 on; the holdout
(2025 onward) is spent by the user, not by the agent.

Step 9 depends only on steps 1, 2 (cash yield on collateral) and 4 (broker adapter for live).
It does not need the stock universe, SEC data or the fast path, so it can move up to any
point after step 4.

## Status (2026-10-04)

Steps 1, 2, 3, 4 and 9 are built, tested (89 tests) and deployed. Step 4's month of paper trading
starts with the first scheduled decision on 2026-10-30; until then the live cycle has been
checked by a dry-run decision, a paper order submit and cancel, and unit tests, not by a full
session.

Changes from the plan made while building:

- Live orders go out at 15:45, the time the backtest fills at, rather than 15:40.
- Option orders are limit orders: priced from the last 30-minute bar before the cutoff, minus
  or plus half the spread (5% of price, at least $0.01). The backtest fills one only if the
  15:30-16:00 bar traded through the limit.
- Put writing runs on XLF, not SPY: a cash-secured SPY put needs over $50,000 of cash, more
  than the $20,000 account. XLF puts need about $4,000 each.
- Alpaca's paper account would not lower its options level below 3, so cash-secured puts are
  enforced by btest (backtest and live), not by the broker.

### Baselines

Lab runs on the website, $20,000 start, fractional shares, idle cash at the T-bill rate. Every
2016-2024 strategy trailed SPY on return in that bull market. All except dual momentum had much
smaller drawdowns.

| Run | Strategy | Window | CAGR | Sharpe | Max drawdown | Benchmark CAGR / drawdown |
|---|---|---|---|---|---|---|
| 12 | baseline/buy_hold (SPY) | 2016-2024 | 13.8% | 0.73 | -32.1% | SPY 14.5% / -33.8% |
| 13 | portfolio/trend_gtaa | 2016-2024 | 5.1% | 0.51 | -7.6% | SPY 14.5% / -33.8% |
| 14 | portfolio/trend_gtaa | 2016-2024 | 5.1% | 0.51 | -7.6% | 60/40 9.3% / -21.7% |
| 15 | portfolio/dual_momentum | 2016-2024 | 6.7% | 0.37 | -33.7% | SPY |
| 16 | portfolio/sector_momentum | 2016-2024 | 5.3% | 0.30 | -22.5% | SPY |
| 17 | mean_reversion/rsi2_basket | 2016-2024 | 4.1% | 0.39 | -9.8% | SPY |
| 18 | calendar/turn_of_month | 2016-2024 | 4.4% | 0.38 | -9.2% | SPY |
| 19 | risk/risk_parity | 2016-2024 | 4.0% | 0.32 | -19.6% | 60/40 9.3% / -21.7% |
| 20 | options/put_write (XLF) | Feb-Dec 2024 | 12.0% | 1.70 | -2.7% | SPY 23.5% / -8.4% |
| 21 | baseline/buy_hold (SPY) | Feb-Dec 2024 | 23.5% | 1.35 | -8.3% | SPY 23.5% / -8.4% |

Buy-and-hold trails the SPY benchmark slightly because dividends arrive as cash (earning
T-bills) instead of being reinvested.

## Decisions (2026-10-04)

1. **History:** 2016-2024 is enough for the stock strategies for now. No paid price data.
2. **Options:** in scope (step 9). Alpaca's options history starts in February 2024 and the
   holdout starts 2025-01-01, so put writing gets about ten months of development data. The
   Cboe PutWrite index serves as a long-history check; a paid options source (Massive, from
   2014) stays an option if ten months proves too thin.
3. **Account:** cash only for now. Alpaca opens every account as a margin account and has no
   separate cash account type. The equivalent is three settings on
   `PATCH /v2/account/configurations`
   ([docs](https://docs.alpaca.markets/us/reference/patchaccountconfig-1)):
   `max_margin_multiplier: "1"`, `no_shorting: true`, `max_options_trading_level: 1` (covered
   calls and cash-secured puts). The same call turns margin back on later. The backtest
   matches it with `allow_short = False` and no leverage.
