# Strategies for a $20k account, and what btest needs to backtest them

October 4, 2026. Research notes plus a gap analysis against btest at commit `d979aa8`.

![What btest adds to backtest portfolio strategies: a universe and daily-bar store feed a
portfolio engine with a rebalance hook, order types, fractional shares and a margin model, then
walk-forward and deflated-Sharpe checks](2026-10-04-strategy-gaps.png)

Diagram source: [`2026-10-04-strategy-gaps.html`](2026-10-04-strategy-gaps.html).

## Constraints that come with $20k

**The pattern day trader rule no longer applies.** The SEC approved FINRA's amendments to Rule
4210 on April 14, 2026, removing the $25,000 minimum and the pattern day trader designation in
favour of an intraday margin requirement, effective June 4, 2026
([Alpaca's announcement](https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/),
[SEC filing SR-FINRA-2025-017](https://www.sec.gov/files/rules/sro/finra/2026/34-105226.pdf)).
Alpaca switched on June 4 and removed `pattern_day_trader` and `daytrade_count` from its account
object. Intraday strategies are open to a $20k margin account; a cash account still waits for
settlement (T+1) before reusing sale proceeds.

**Whole shares cost real tracking error.** A 20-position portfolio puts about $1,000 in each
name. Rounding down to whole shares of a $700 stock leaves a 30% weight error in that name.
Alpaca supports fractional shares, so the backtest should too.

**Commissions are zero; spreads are not.** Alpaca charges no commission on US equities. The
costs that remain are the bid-ask spread, the SEC fee on sales (already modelled) and the FINRA
trading activity fee (not modelled; a fraction of a cent per hundred shares sold). Order size at $20k
has no market impact on liquid ETFs, so spread and slippage per trade are the whole cost model.
High-turnover strategies live or die on that number.

**Taxes favour low turnover.** In a taxable account, a strategy that trades monthly realises
short-term gains taxed as income. The backtest does not need a tax engine, but turnover and
average holding period belong on every run page so this is visible.

**Published edges shrink.** McLean and Pontiff found anomaly returns fall about 26% out of
sample and 58% after publication
([J. Finance 2016](https://doi.org/10.1111/jofi.12365)). Expect less than the papers report.

## Candidate strategies

Ranked by how well they suit a $20k account, how sturdy the evidence is, and how cheaply btest
can test them. "Status" says whether btest already has a version.

| # | Strategy | Rule (short) | Rebalance | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Multi-asset trend (GTAA) | Hold each of ~5 asset-class ETFs (US stocks, intl stocks, bonds, REITs, commodities) at 20% when above its 10-month SMA, else cash | Monthly | [Faber 2007](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461); [Moskowitz, Ooi, Pedersen 2012](https://doi.org/10.1016/j.jfineco.2011.11.003) | Single-asset only (`trend/sma_200`) |
| 2 | Dual momentum (GEM) | Hold US stocks or intl stocks, whichever had the higher 12-month return, if that return beats T-bills; else bonds | Monthly | [Antonacci 2012](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750) | Absolute half only (`trend/momentum_12m`) |
| 3 | Sector / ETF relative momentum | Hold the top 3 of the 11 sector ETFs by 6-12 month return, optionally with a trend filter | Monthly | [Moskowitz and Grinblatt 1999](https://doi.org/10.1111/0022-1082.00146) | None |
| 4 | Short-term mean reversion basket | RSI(2) or IBS pullback buys across SPY, QQQ, IWM, DIA, each held a few days | Daily | Connors and Alvarez, *Short Term Trading Strategies That Work* (2008) | Single-asset (`mean_reversion/rsi2`) |
| 5 | Inverse-volatility / risk parity with vol target | Weight a stock/bond/gold ETF set by inverse 60-day vol, scale to a target portfolio vol | Monthly | [Moreira and Muir 2017](https://doi.org/10.1111/jofi.12513) | Single-asset (`risk/vol_target`) |
| 6 | Stock cross-sectional momentum | Hold the top 20 large caps by 12-1 month return | Monthly | [Jegadeesh and Titman 1993](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x) | None |
| 7 | Turn of month | Hold SPY from the last trading day of the month through the third trading day of the next, cash otherwise | Monthly | [McConnell and Xu 2008](https://doi.org/10.2469/faj.v64.n2.11) | None |
| 8 | Overnight hold | Buy SPY or QQQ at the close, sell at the next open | Daily | [Lou, Polk, Skouras 2019](https://doi.org/10.1016/j.jfineco.2019.03.011) | None |
| 9 | Opening range breakout | Trade QQQ in the direction of the first 5-minute bar, stop at its other side, exit at 10R or the close | Intraday | [Zarattini and Aziz 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622) | Long-only 30-minute version (`intraday/opening_range`), no stop |
| 10 | ETF pairs | Trade the spread of a cointegrated ETF pair (e.g. two overlapping sector ETFs), long one, short the other | Daily | [Gatev, Goetzmann, Rouwenhorst 2006](https://doi.org/10.1093/rfs/hhj020) | None |

Notes on the weaker entries:

- **#8 overnight hold** trades every day, so a 1 bp per-side spread costs about 5% a year. The
  effect is real in the data, but the net result depends almost entirely on the cost model.
- **#9 opening range breakout** reports results with commission but no spread or slippage and
  no out-of-sample period. An independent replication found break-even at about 2.2 cents per
  share of slippage and most of the profit concentrated in 2022
  ([replication](https://github.com/giovannibrusco/zarattini-2023-orb-qqq)). Worth testing
  because btest has minute bars, not worth trading on the paper's numbers.
- **#10 pairs** needs shorting, which brings borrow fees and margin into the model.

Left out on purpose:

- **Options income (covered calls, cash-secured puts, the wheel).** Testing these needs a
  historical options chain. Alpaca's options history starts in February 2024
  ([Alpaca docs](https://docs.alpaca.markets/us/docs/historical-option-data)), which is less
  than one year of data before the holdout. A real test needs a paid source (ORATS, Cboe
  DataShop) and a separate pricing engine. Revisit only if the user wants options.
- **Post-earnings drift and other fundamentals-driven strategies.** They need point-in-time
  earnings data that btest has no source for.
- **Crypto.** Alpaca offers it, but 24/7 trading breaks btest's NYSE session calendar
  throughout the engine and the bar aggregation.

## What btest has today

- Minute bars from Alpaca SIP since 2016-01-01 for three symbols (`SPY`, `META`, `NVDA` in
  `btest.toml`), stored as Parquet; splits, dividends, NYSE calendar and T-bill rates in
  Postgres.
- Bars aggregated to 5m through 1D; decisions at bar close, market fills at the next bar's open.
- An event engine (`engine.py`) that already accepts several symbols, and a numba fast path
  (`fast.py`) and sweeps (`sweep.py`) that handle one symbol.
- Long-only by default. `allow_short` exists but shorts have no borrow cost and no margin check.
- Whole shares only; buys capped by cash.
- Holdout from 2025-01-01, so development uses 2016-2024 (nine years, with bear markets in 2020
  and 2022 but not 2008).

## Gaps

Each gap lists the strategies it blocks.

### G1. ETF universe (blocks 1, 2, 3, 4, 5, 7, 10)

Add the ETFs to `btest.toml` and ingest them. A working set of about 25:

- Asset classes: `SPY QQQ IWM DIA EFA EEM VNQ GLD DBC TLT IEF SHY BIL AGG LQD HYG`
- Sectors: `XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC`

`XLRE` starts in October 2015 and `XLC` in June 2018, so universe strategies must handle a
symbol joining mid-backtest. The three current symbols take 124 MB of Parquet, so 25 ETFs need about
1 GB on the worker's `/data` volume.

### G2. Portfolio rebalance hook (blocks 1, 2, 3, 5, 6, 10)

`Engine.run` walks events sorted by `(ts, symbol)` and calls `on_bar` once per symbol. When
`on_bar` fires for the first symbol at a timestamp, the other symbols' bars at that timestamp
have not been applied yet, so a cross-sectional rank sees a mix of today's and yesterday's
closes. Add `on_bars(ctx, bars: dict[str, Bar])`, called once after every symbol's bar for a
timestamp has been applied. Daily bars are stamped with their first minute, so a symbol with a
missing 09:30 minute gets a different timestamp; align on `date` for 1D bars.

### G3. Batch rebalancing (blocks 1, 2, 3, 5, 6)

Pending orders fill in symbol order. A rotation that sells A and buys B fills B first if B sorts
first, finds no cash, and the cash cap shrinks the buy. Add `ctx.rebalance({symbol: weight})`
that computes all targets from one equity figure and fills sells before buys at the next open.

### G4. Fractional shares (blocks 6; improves 1-5)

A `Config.fractional` flag that drops the `math.floor` in `order_target_percent`, the cash cap
and the split adjustment. Off by default so existing runs reproduce.

### G5. Cash yield and benchmarks (improves 1, 2, 5, 7)

Trend strategies spend months in cash. Today idle cash earns nothing, which understates them
against SPY. Credit idle cash daily at the T-bill rate already in `market.rate` (behind a flag,
since Alpaca's brokerage cash yield depends on the account). Also let a run choose its benchmark:
a 60/40 SPY/AGG mix is the fair comparison for GTAA, not SPY alone.

### G6. Order types (blocks 7, 8, 9)

- **Market-on-close and market-on-open.** Overnight hold and turn of month trade at the close.
  With 1D bars the next fill is tomorrow's open, which is a different strategy.
- **Stop and limit orders** with an intrabar fill rule: a stop triggers when a later minute's
  high or low crosses it, fills at the stop price or the bar's open if it gapped through. The
  minute data makes this testable for 5m strategies.
- **Brackets** (entry plus stop plus target), which ORB needs.

### G7. Short selling and margin (blocks 9 short side, 10)

Model Reg T buying power (50% initial, 25-30% maintenance), a borrow fee as an annual rate on
short market value (easy-to-borrow ETFs run well under 1%), and reject or liquidate on a margin
breach. Short dividends already debit cash correctly because `_corporate_actions` multiplies by
a negative position.

### G8. Spread cost per symbol (improves 4, 8, 9)

Replace the single `slippage_bps` with a per-symbol half-spread table plus a fixed slippage
term, and add the FINRA TAF on sales. Sweep the cost to find each strategy's break-even, the
way the ORB replication did.

### G9. Portfolio fast path (speeds up sweeps for 1-7)

`signals()` returns one weight series for one symbol. A portfolio version returns a
`(bars, symbols)` weight matrix; the numba kernel loops symbols inside each bar, applies G3's
sells-first rule, and keeps parity with the event engine through `btest parity`. Without it,
sweeps over multi-asset strategies fall back to the event engine (slower, still correct).

### G10. Overfitting checks (applies to all)

- **Walk-forward**: split 2016-2024 into rolling train and test windows, pick the best sweep
  setting on each train window, and report the stitched test-window equity.
- **Deflated Sharpe ratio**: adjust the best sweep result's Sharpe for the number of settings
  tried ([Bailey and López de Prado 2014](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)).
  btest already records sweep sizes, so the trial count is available.

### G11. Survivorship-free stock universe (blocks 6 only)

Stock momentum needs point-in-time index membership plus price history for companies that were
delisted or acquired. Testing on today's S&P 500 members inflates returns. Options:

- **Norgate Data**: paid subscription, survivorship-free US stocks with historical index
  membership. The standard retail answer.
- **Free constituent lists** (for example, community-maintained S&P 500 membership history on
  GitHub) joined to Alpaca bars. Whether Alpaca serves history for delisted tickers is
  unverified; check before relying on it.

This also calls for a daily-bar store: 500 stocks of minute bars would be about 20 GB,
and a monthly strategy gains nothing from minutes. This is the largest gap and unblocks one
strategy, so it goes last.

## Order of work

| Phase | Gaps | Unlocks | Size |
|---|---|---|---|
| A | G1, G2, G3, G4, G5 | 1, 2, 3, 4 (basket), 5, 7 (at next open) | Medium |
| B | G6, G8 | 7 (at close), 8, 9 (long side) | Medium |
| C | G7 | 9 (both sides), 10 | Medium |
| D | G9, G10 | Fast multi-asset sweeps, walk-forward, deflated Sharpe | Medium |
| E | G11 | 6 | Large; needs a data-source decision and possibly a subscription |

After phase A, btest can test seven of the ten strategies. Phase D can run in parallel with B
and C once G2 and G3 settle the portfolio semantics, since the fast path must copy them.

## Decisions for the user

- Whether to pay for a survivorship-free stock dataset (phase E), or skip stock momentum.
- Whether the live account will be margin or cash. A cash account rules out shorts (10, half of
  9) and adds settlement delays the engine would need to model.
- Whether options are in scope at all. They are excluded above.
