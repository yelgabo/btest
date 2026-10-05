# Strategies for a $20k account, and what btest needs to backtest them

October 4, 2026. Research notes plus a gap analysis against btest at commit `d979aa8`.

![What btest adds to backtest the candidate strategies: a universe list, stock and options
data feed a portfolio engine with a rebalance hook, order types, fractional shares and a margin model, then
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

Ranked on three things only: how strong and durable the published evidence is, whether the edge
survives at $20k (costs, capacity, shorting), and how bad the worst case is. What btest can test
today is not a criterion; missing data and features are listed under Gaps with their cost. An
earlier draft of this doc filtered by btest's current data and left out factor, event-driven
and options strategies; this version corrects that.

| # | Strategy | Rule (short) | Rebalance | Evidence | btest today |
|---|---|---|---|---|---|
| 1 | Multi-asset trend following | Hold each of 10-20 ETFs (stocks, bonds, gold, commodities, intl) when its trend is up, size by volatility, cash otherwise | Monthly | [Moskowitz, Ooi, Pedersen 2012](https://doi.org/10.1016/j.jfineco.2011.11.003); [Faber 2007](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461) | Single-asset only (`trend/sma_200`) |
| 2 | Stock momentum | Hold the top 20-30 large and mid caps by 12-month return excluding the last month | Monthly | [Jegadeesh and Titman 1993](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x); crash risk in [Daniel and Moskowitz 2016](https://doi.org/10.1016/j.jfineco.2015.12.002) | No stock universe |
| 3 | Multi-factor stocks | Rank stocks on a mix of profitability, value and momentum; hold the top 20-30 | Monthly or quarterly | [Novy-Marx 2013](https://doi.org/10.1016/j.jfineco.2013.01.003); [Asness, Frazzini, Pedersen 2019](https://doi.org/10.1007/s11142-018-9470-2) | No fundamentals |
| 4 | Post-earnings drift | Buy stocks with the largest positive earnings surprise after the report, hold about 60 days | Daily scan | [Bernard and Thomas 1989](https://doi.org/10.2307/2491062); decay in large caps per [Martineau 2022](https://doi.org/10.1561/104.00000122) | No earnings data |
| 5 | Put writing on the index | Sell a cash-secured SPY put about a month out, repeat at expiry | Monthly | Variance risk premium, [Carr and Wu 2009](https://doi.org/10.1093/rfs/hhn038); Cboe's PutWrite (PUT) index since 1986 | No options data or engine |
| 6 | Insider buying | Buy after clusters of open-market purchases by officers and directors, skipping routine ones | Daily scan | [Cohen, Malloy, Pomorski 2012](https://doi.org/10.1111/j.1540-6261.2012.01740.x) | No Form 4 data |
| 7 | ETF relative momentum | Dual momentum (US vs intl stocks vs bonds) or top 3 sector ETFs | Monthly | [Antonacci 2012](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750); [Moskowitz and Grinblatt 1999](https://doi.org/10.1111/0022-1082.00146) | Absolute half only (`trend/momentum_12m`) |
| 8 | Short-term mean reversion | RSI(2) or IBS pullback buys across index ETFs, held a few days | Daily | Connors and Alvarez, *Short Term Trading Strategies That Work* (2008) | Single-asset (`mean_reversion/rsi2`) |
| 9 | Calendar effects | Hold SPY around the turn of the month and in the 24 hours before FOMC announcements | Monthly | [McConnell and Xu 2008](https://doi.org/10.2469/faj.v64.n2.11); [Lucca and Moench 2015](https://doi.org/10.1111/jofi.12196) | None (FOMC dates missing) |
| 10 | Volatility targeting overlay | Scale any of the above to a target portfolio volatility | Daily or weekly | [Moreira and Muir 2017](https://doi.org/10.1111/jofi.12513) | Single-asset (`risk/vol_target`) |

Why this order:

- **#1 and #2** have the longest and broadest evidence of any strategy a retail account can run.
  Trend following's main value is losing less in long bear markets. Momentum's main risk is
  sudden crashes when markets rebound sharply (2009).
- **#3** combines signals that tend to have bad years at different times. Value alone had a poor
  decade from about 2010; profitability and momentum carried the mix.
- **#4 and #6** are where a small account has an advantage. The effects are strongest in small
  and mid caps that large funds can't trade in size. Post-earnings drift has largely disappeared
  in large caps since the mid-2000s (Martineau 2022), so the test must be run on smaller stocks
  with realistic spreads.
- **#5** earns an equity-like return with lower day-to-day volatility, but loses heavily in
  crashes (a put writer took most of the market's loss in 2008 and March 2020). It is ranked on
  its long record, not because it is safe.
- **#7 and #8** are cruder versions of #1 and #2 with fewer independent bets.
- **#9** is cheap and well documented, but in the market only a few days a month, so it is
  better as a component than a whole portfolio.
- **#10** is an overlay, not a strategy on its own.

Considered and ranked below these, on merit:

- **ETF pairs and stat arb.** Profits from the classic pairs rule have shrunk steadily since the
  1990s ([Do and Faff 2010](https://doi.org/10.2469/faj.v66.n4.1)), and the short side costs
  borrow fees and margin.
- **Crypto trend following.** Strong results in a short history (about ten years of liquid
  markets) dominated by a few bubbles; promising but less evidence than #1.
- **Overnight hold** (buy at the close, sell at the open). Most of the US equity premium has
  arrived overnight ([Lou, Polk, Skouras 2019](https://doi.org/10.1016/j.jfineco.2019.03.011)),
  but trading it means 252 round trips a year, short-term taxes on every gain and full gap
  risk, while buy-and-hold already collects that return.
- **Opening range breakout** on QQQ
  ([Zarattini and Aziz 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622)).
  No spread or slippage in the paper, no out-of-sample period; a replication found break-even
  at about 2.2 cents per share of slippage and most of the profit in 2022
  ([replication](https://github.com/giovannibrusco/zarattini-2023-orb-qqq)).
- **Market making, HFT, latency arbitrage.** Not available at retail; the edge is speed and
  order flow.

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

### G1. ETF universe (blocks 1, 7, 8, 9, 10)

Add the ETFs to `btest.toml` and ingest them. A working set of about 25:

- Asset classes: `SPY QQQ IWM DIA EFA EEM VNQ GLD DBC TLT IEF SHY BIL AGG LQD HYG`
- Sectors: `XLK XLF XLV XLE XLI XLY XLP XLU XLB XLRE XLC`

`XLRE` starts in October 2015 and `XLC` in June 2018, so universe strategies must handle a
symbol joining mid-backtest. The three current symbols take 124 MB of Parquet, so 25 ETFs need about
1 GB on the worker's `/data` volume.

### G2. Portfolio rebalance hook (blocks 1, 2, 3, 4, 6, 7)

`Engine.run` walks events sorted by `(ts, symbol)` and calls `on_bar` once per symbol. When
`on_bar` fires for the first symbol at a timestamp, the other symbols' bars at that timestamp
have not been applied yet, so a cross-sectional rank sees a mix of today's and yesterday's
closes. Add `on_bars(ctx, bars: dict[str, Bar])`, called once after every symbol's bar for a
timestamp has been applied. Daily bars are stamped with their first minute, so a symbol with a
missing 09:30 minute gets a different timestamp; align on `date` for 1D bars.

### G3. Batch rebalancing (blocks 1, 2, 3, 4, 6, 7)

Pending orders fill in symbol order. A rotation that sells A and buys B fills B first if B sorts
first, finds no cash, and the cash cap shrinks the buy. Add `ctx.rebalance({symbol: weight})`
that computes all targets from one equity figure and fills sells before buys at the next open.

### G4. Fractional shares (blocks 2, 3, 4, 6; improves 1, 7)

A `Config.fractional` flag that drops the `math.floor` in `order_target_percent`, the cash cap
and the split adjustment. Off by default so existing runs reproduce.

### G5. Cash yield and benchmarks (improves 1, 7, 9)

Trend strategies spend months in cash. Today idle cash earns nothing, which understates them
against SPY. Credit idle cash daily at the T-bill rate already in `market.rate` (behind a flag,
since Alpaca's brokerage cash yield depends on the account). Also let a run choose its benchmark:
a 60/40 SPY/AGG mix is the fair comparison for GTAA, not SPY alone.

### G6. Order types (improves 9; needed for the overnight and ORB checks)

- **Market-on-close and market-on-open.** Overnight hold and turn of month trade at the close.
  With 1D bars the next fill is tomorrow's open, which is a different strategy.
- **Stop and limit orders** with an intrabar fill rule: a stop triggers when a later minute's
  high or low crosses it, fills at the stop price or the bar's open if it gapped through. The
  minute data makes this testable for 5m strategies.
- **Brackets** (entry plus stop plus target), which ORB needs.

### G7. Short selling and margin (only the lower-ranked pairs and ORB short side)

Model Reg T buying power (50% initial, 25-30% maintenance), a borrow fee as an annual rate on
short market value (easy-to-borrow ETFs run well under 1%), and reject or liquidate on a margin
breach. Short dividends already debit cash correctly because `_corporate_actions` multiplies by
a negative position.

### G8. Spread cost per symbol (blocks honest tests of 4, 6, 8)

Replace the single `slippage_bps` with a per-symbol half-spread table plus a fixed slippage
term, and add the FINRA TAF on sales. Post-earnings drift and insider buying live in small and
mid caps, where spreads are several times wider than on SPY; a flat 1 bp would overstate them. Sweep the cost to find each strategy's break-even, the
way the ORB replication did.

### G9. Portfolio fast path (speeds up sweeps for 1, 2, 3, 7)

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

### G11. Survivorship-free stock prices (blocks 2, 3, 4, 6)

Every stock strategy needs price history for companies that were later delisted or acquired,
plus point-in-time index membership. Testing on today's S&P 500 members inflates returns.

**Alpaca already has the delisted prices from 2016.** Checked on 2026-10-04: daily bars for
Twitter, Activision, SVB, First Republic, Bed Bath & Beyond, Xilinx and Citrix all run from
2016-01-04 to each company's last trading day. Alpaca's asset list does not include most of
these tickers, so it cannot say which stocks existed on a given date. The missing piece for
2016 onward is a point-in-time membership list (for example S&P 500 or Russell 1000
constituents by date) to request bars from. Ticker reuse, where a recycled symbol could join
two companies' histories, has not been checked.
These are daily strategies, so this means a new daily-bar store next to the minute Parquet
(500 stocks of minute bars would be about 20 GB and a monthly rebalance gains nothing from
minutes).

Daily data has a second benefit: it reaches back past 2016. Alpaca's minute history starts in
2016, which leaves 2016-2024 for development with only the short 2020 crash and the 2022 bear
market. Daily history from 1998 adds 2000-2002 and 2008, which is where trend and momentum
strategies show their real behaviour.

### G12. Point-in-time fundamentals (blocks 3, 4)

Financial statement values stamped with the date they were filed, so a backtest only sees
numbers the market had at the time. Restated figures must not leak backwards.

### G13. Event data (blocks 4, 6, 9)

- Earnings announcement dates and reported earnings, for the surprise in #4. The surprise can
  be measured against the same quarter a year earlier (the method in Bernard and Thomas 1989),
  which avoids buying analyst-consensus data.
- SEC Form 4 insider transactions for #6, with the transaction code that separates open-market
  purchases from grants and option exercises.
- FOMC meeting dates for #9, from the Federal Reserve's published calendar.

### G14. Options chains and an options engine (blocks 5)

Historical option quotes (bid, ask, strike, expiry) and engine support for option positions:
cash-secured collateral, daily marks from quotes, expiry, assignment into shares. This is the
largest engine change on the list. Cboe's PutWrite (PUT) index tracks this strategy and can serve
as a sanity check for #5 before any of this is built.

### Data sources for G11-G14

Free sources cover everything except options before 2024. Each was queried on 2026-10-04.

| Need | Free source | What it gives | Limits |
|---|---|---|---|
| Stock prices incl. delisted (G11) | Alpaca, already in btest | Daily and minute bars from 2016 to each company's last day | Asset list omits dead tickers; nothing before 2016 |
| Index membership (G11) | [fja05680/sp500](https://github.com/fja05680/sp500) | S&P 500 members by date since 1996 | Community-maintained; S&P 500 only |
| Fundamentals (G12) | [SEC companyfacts API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`) | Every reported financial line per company, each tagged with its filing date, so point-in-time works; delisted companies included | XBRL from 2009; tag names vary between companies and need mapping |
| Earnings dates (G13) | SEC submissions API (`data.sec.gov/submissions/CIK##########.json`) | 8-K filings with item 2.02 (earnings release) and their dates | Reported earnings come from companyfacts; no analyst consensus |
| Insider trades (G13) | [SEC insider transactions data sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets) | Forms 3, 4 and 5 as quarterly tables from 2006 | Needs filtering to open-market purchases (code P) |
| FOMC dates (G13) | [Federal Reserve calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | Meeting dates | Typed in once a year |
| Options (G14) | Alpaca options bars, already in btest's account | Daily and minute trade bars per contract from February 2024 | Trade prices, not bid/ask; under a year before the holdout |
| Sanity checks | [Ken French data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) | Monthly returns of momentum, value and profitability factors back to the 1920s | Factor returns, not tradable portfolios; useful to check a btest result's direction |

SEC requests need a User-Agent header with a contact address and must stay under 10 requests a
second.

Paid sources only buy time or older history:

| Source | Adds over the free set | Cost |
|---|---|---|
| [Sharadar bundle](https://data.nasdaq.com/databases/SFA) | Cleaned fundamentals, insiders and events; prices from 1998 | Shown after login |
| [Norgate Data Platinum](https://norgatedata.com/stockmarketpackages.php) | Prices and index membership from 1990, delisted included | $630 a year |
| [Massive](https://massive.com/pricing), ORATS, Cboe DataShop | Options history before 2024 (Massive from 2014) | Paid; options prices not public |

## Order of work

| Phase | Gaps | Unlocks | Size |
|---|---|---|---|
| A | G1, G2, G3, G4, G5 | 1, 7, 8, 10, and 9 (turn of month at the next open) | Medium |
| B | G11, G12, G13, G8 | 2, 3, 4, 6, and 9 (FOMC) | Large; 2016+ stock momentum needs no purchase |
| C | G14 | 5 | Large; needs options data |
| D | G9, G10 | Fast multi-asset sweeps, walk-forward, deflated Sharpe | Medium; runs alongside B |
| E | G6, G7 | Close-of-day fills, and the ruled-out overnight, ORB and pairs checks | Medium |

Phase A needs no new data and covers the top-ranked strategy. Phase B covers four of the top
six. Its first step, stock momentum on Alpaca prices plus a free membership list, needs no
purchase; fundamentals, events and pre-2016 history are where a purchase comes in.

## Decisions for the user

- Whether 2016 onward is enough history for the stock strategies. Everything for 2016 onward
  is free; a paid source is only needed for older history or to skip the EDGAR parsing work.
- Whether options (#5) are worth a paid options dataset and the largest engine change.
- Whether the live account will be margin or cash. A cash account still allows #5
  (cash-secured puts) but rules out shorting.
