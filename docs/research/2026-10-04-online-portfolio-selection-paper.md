# Paper review: "Online Quantitative Trading Strategies" (Lahanis, Liu, Zhou, NYU Stern)

Draft 4, October 5, 2026. Supersedes drafts 1 (commit 4f1fa05), 2 (unpublished) and 3 (commit
f7d034c); see "Corrections". Draft 2 was reviewed by three independent reviewers and draft 3 by
a fourth; their findings and what was done with each are listed under "Review record".

Sources: `Glucksman_Lahanis.pdf` (20 pages, Glucksman Fellowship, May 2025); the authors' code
and data, [nglahani/Online-Quantitative-Trading-Strategies](https://github.com/nglahani/Online-Quantitative-Trading-Strategies)
at commit `7c2e88d` (MIT license). Every number below comes from a script in
`docs/research/olps-replication/` (setup in its README); the raw outputs are in
`docs/research/olps-replication/outputs/`.

## Summary

1. **The paper's results reproduce exactly from the authors' published data and code.** Their
   repository contains the price data (93 NASDAQ-100 stocks, 1998-01-02 to 2009-12-31). Running
   their functions gives CWMR 1590.3818, PAMR 788.2571, Anticor 36.8868, FTRL 15.2490, CRP
   12.1584 and buy-and-hold 9.1742, matching Tables 3 and 4.
2. **In that sample, mean reversion keeps much of its return after costs or a one-day delay;
   its risk-adjusted edge is more fragile.** Against an equal-weight portfolio rebalanced daily
   (CRP, 23.2% a year), CWMR compounds 43.6% a year at 10 bp per dollar traded and 45.6% with a
   one-day delay, but its Sharpe ratio advantage is significant only without frictions
   (p < 0.0001; p = 0.29 at 10 bp, p = 0.11 with the delay). PAMR's advantage survives the delay
   (p = 0.0002) but not the delay plus 5 bp (p = 0.49). The parameters were selected on this
   sample (see section 1), so this is in-sample evidence.
3. **Out of sample (2016-2024) the effect is small and not statistically detectable.** On 16
   liquid equity ETFs, CWMR beat SPY before costs from 3 of 8 start years (2016, 2018, 2020).
   From the 2016 start it still led after measured spreads when trading at the close (15.7%
   against 14.5%) but trailed when trading at 15:45 (13.8%). It beats CRP in most but not all
   tested conditions (not at 5 bp, not at 15:45 timing plus 1 bp, not from a 2022 start). On current
   NASDAQ-100 members, CWMR and PAMR have lower Sharpe ratios than CRP at every cost tested,
   including zero. None of the tested 2016-2024 comparisons is statistically significant.
4. **Five of the paper's reported strategies differ from the algorithms they are named after.**
   OLMAR and EG never change their target weights, so both are CRP (the paper's tables show
   identical numbers for all three). FTRL's edge over CRP disappears when the 32 tickers with
   incomplete data are removed. CWMR and RMR are modified versions of the published methods.

The paper discloses that it ignores trading costs and that 1998-2010 may not represent recent
markets (section 6.4). Points 2 and 3 quantify those two disclosed limitations, against the
abstract's conclusion that these methods "provide superior risk-adjusted returns".

## Definitions used throughout

- **CRP**: equal weight in every stock or ETF, reset to equal weight every day (the paper's
  benchmark). "Monthly CRP" resets only at month end.
- **Method A**: the paper's method. Weights computed from day t's close earn the return from day
  t's close to day t+1's close.
- **One-day delay**: weights computed from day t's close earn day t+1's close to day t+2's close.
  Tradable in practice with market-on-close orders on day t+1.
- **btest timing**: weights computed at 15:30 New York time from data through the 15:14 minute,
  filled at the 15:45 minute's open. This is what btest's live system does.
- **Cost**: charged on every dollar traded (the sum of absolute weight changes from drifted
  weights), in basis points (bp) per dollar traded. "Measured spreads" applies each symbol's
  measured half-spread (see below).
- **Turnover**: dollars traded per year divided by average portfolio value, counting buys and
  sells.
- **Sharpe ratio**: labelled per table as "rf 5%" (excess over a constant 5%, the paper's
  convention, section 3.2), "no rf" (raw), or "T-bill" (excess over the 3-month T-bill rate,
  btest's convention).
- **Paired test**: Jobson-Korkie test with Memmel's correction on daily returns of two
  strategies over the same days; it accounts for their correlation (0.71-0.98 in these tests).

## 1. The paper's own sample, 1998-2009 (`paper_data.py`)

93 tickers, 3,019 days. Parameters are the paper's Exhibit A values, which equal the code
defaults for every algorithm in this section (they differ for RMR's eta, 20 against 30, and the
nearest-neighbour count, 3 against 5, neither used here).

How the parameters were chosen: the paper describes walk-forward validation (section 5.1.2). In
the code, `tune_strategy(use_walk_forward=False)` makes it optional; the saved tuning results
report averages over validation windows, consistent with walk-forward having been used, but all
windows lie inside 1998-2009. The selected parameters were therefore chosen with this sample.
The paper also reports Anticor's alpha as 2.5 (Exhibit A) while its tuning grid shows only 1.5
and 2.0 (Table 2).

CAGR (wealth multiple), Sharpe rf 5% / no rf:

| Strategy | Method A | A + 1 bp | A + 5 bp | A + 10 bp | One-day delay | Delay + 5 bp |
|---|---|---|---|---|---|---|
| CRP | 23.2% (12.2x), 0.76 / 0.95 | 23.1% | 22.9% | 22.6% | 23.2% | 22.9% |
| CWMR | 85.0% (1,590x), 1.75 / 1.88 | 80.4% (1,174x) | 63.0% (349x) | 43.6% (76x), 1.05 / 1.18 | 45.6% (90x), 1.13 / 1.28 | 28.5% (20x), 0.76 / 0.91 |
| PAMR | 74.5% (788x), 1.63 / 1.77 | 70.1% | 53.5% | 35.1% (37x), 0.90 / 1.04 | 51.9% (149x), 1.26 / 1.41 | 33.9% (33x), 0.89 / 1.03 |
| Anticor | 35.1% (37x), 1.02 / 1.19 | 31.8% | 19.0% | 4.8% (1.8x) | 30.0% (23x) | |
| FTRL | 25.5% (15.2x), 1.04 / 1.30 | 25.5% | 25.3% | 25.0% | 25.5% | |

Paired Sharpe tests against CRP (annualized difference, no rf, p):

| | Method A | A + 10 bp | One-day delay | Delay + 5 bp | Delay + 10 bp |
|---|---|---|---|---|---|
| CWMR | +0.94 (p < 0.0001) | +0.23 (0.29) | +0.33 (0.11) | -0.04 (0.86) | |
| PAMR | +0.82 (p < 0.0001) | +0.09 (0.52) | +0.46 (0.0002) | +0.09 (0.49) | -0.29 (0.02) |

Robustness checks on the same data:

- **Two suspected bad prints.** PCAR on 2000-02-16/17 (price ratio 0.536 then 1.943) and XRAY on
  2004-07-22/23 (0.468 then 2.087) are the only spike-and-reverse pairs beyond 0.6/1.6. Setting
  both to 1.0 lowers CWMR from 1,590x to 1,120x (79.7% a year) and PAMR from 788x to 626x.
- **Tickers with data over almost the whole sample (61 of 93).** CWMR method A 85.9% a year;
  one-day delay 30.8%; CRP 21.4%. FTRL falls to 17.2%, below CRP.

## 2. Code findings (authors' repository, commit 7c2e88d)

Verified by reading the code and running it on the paper's data unless stated.

1. **OLMAR's target weights never change.** `olmar()` updates only when `b . MA(price ratios)
   < 0.8`; on the paper's data that quantity never falls below 0.8, and the target changed on 0
   of 3,018 days. OLMAR therefore rebalances to equal weight daily, which is CRP; the paper
   reports identical results for both (12.1584). The function also averages price ratios
   instead of computing Li and Hoi's moving average of prices over the current price.
2. **EG's target weights never change.** `exponential_gradient()` blends the new weights with
   the old as `(1 - smoothing) * old + smoothing * new`, and the paper's smoothing is 0.0
   (Exhibit A). The target changed on 0 of 3,018 days; the paper reports EG identical to CRP
   (12.1584, Sharpe 0.7552, max drawdown -45.19%).
3. **FTRL's edge depends on the tickers with incomplete data.** On all 93 tickers FTRL returns
   25.5% against CRP's 23.2%; on the 61 tickers with near-complete data it returns 17.2% against
   21.4%. The 32 removed tickers include the 20 held at a flat placeholder price (ratio 1.0)
   before they list; we have not isolated whether the placeholder cells themselves drive the
   difference.
4. **CWMR is a modified algorithm.** The docstring calls it "a simplified version of CWMR with
   an additional learning rate factor." The step size is a passive-aggressive closed form
   without Li et al.'s confidence term, the confidence parameter enters the covariance update
   directly, a learning-rate factor is added, and the mean-centering of the update is omitted.
5. **RMR is modified.** It takes the L1-median of past price ratios divided by the last price
   ratio; Huang et al.'s RMR takes the L1-median of past prices divided by the current price.
   (Read in the code; not run.)
6. **Missing prices are forward-filled.** A ticker with no data on a day keeps its last price
   (ratio 1.0). In the paper's data, 20 tickers have more than 20 placeholder days before
   listing, and five stop trading during the sample (APCC, BGEN, MEDI, NXTL, SEBL, all acquired,
   so their last prices are close to deal prices).
7. **No look-ahead in the wealth calculation.** Weights for day t use price ratios through
   day t-1.

Not verified: whether the source minute files include after-hours trades, which would make the
daily "close" an after-hours print (`calculate_price_relative_vectors` takes each file's last
row).

From the paper itself: "best stock" is described as the hindsight best but implemented as
yesterday's best (equation 2); the sample data figure shows 2020 dates in a 1998-2010 study;
the stated sample ends 2010, the data ends 2009-12-31.

## 3. Out of sample: 16 equity ETFs, 2016-2024 (`decompose.py`, `their_code.py`)

SPY, QQQ, IWM, DIA, EFA, EEM and 10 sector ETFs (XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB,
XLRE), Alpaca SIP minute bars aggregated to daily, adjusted for splits and dividends,
2016-01-04 to 2024-12-31. The authors' functions with the paper's parameters (not re-tuned).
SPY: 14.5% a year, Sharpe 0.84 no rf, max drawdown -33.8%. CRP: 12.0%.

| CWMR, authors' code | CAGR | Sharpe (no rf) | Max DD | Turnover |
|---|---|---|---|---|
| Method A | 17.5% | 0.91 | -33.1% | 353x |
| Method A + 1 bp | 13.4% | 0.73 | -33.3% | 353x |
| Method A + 5 bp | -1.5% | 0.02 | -44.2% | 353x |
| Method A + measured spreads | 15.7% | 0.83 | | |
| One-day delay | 16.2% | 0.87 | -34.1% | 354x |
| btest timing (see input note) | 16.3% | | | |
| btest timing + 1 bp | 12.3% | | | |

Break-even flat cost against SPY on CAGR: 0.74 bp per dollar traded (method A); 0.43 bp in this
script's emulation of btest timing. The btest engine itself still leads SPY at 0.43 bp (14.9%)
and trails at 0.70 bp (13.8%), so its break-even lies between the two. Measured spreads average
0.70 bp.

Input note: CWMR's result depends on how the day's price ratio is defined. Using 15:14 prices
for every day gives 14.7%; using closing prices for past days and the 15:14 price for the
current day (what a live system sees, and what btest's engine uses) gives 16.3%.

PAMR (authors' code): method A 13.2%; + measured spreads 12.0%; one-day delay 14.3%. Anticor:
method A 10.0%; + measured spreads 7.9%; one-day delay 14.9%.

The one-day delay raises PAMR's and Anticor's returns rather than lowering them, which is not
what a one-day reversal effect predicts; we read the delay results as noise rather than
evidence about the mechanism.

**btest engine** (`strategies/olps/cwmr.py`, a port matching the authors' `cwmr()` to within
7.1e-9 per weight on the paper's data, `port_vs_authors.py`; full-history replay checked
identical to a cached incremental update, `cwmr_cache_check.py`; engine outputs in
`outputs/engine_cwmr.out`): CWMR
16.6% at 0 bp, 14.9% at 0.43 bp, 13.8% at 0.70 bp (Sharpe T-bill 0.77, 0.70, 0.65; SPY 14.5%,
0.73). PAMR 8.9%, OLMAR (Li and Hoi's published form, our implementation) 6.9% and monthly CRP
11.8% at 0.70 bp. Saved as btest runs 35-42 (each strategy at 0 and 0.7 bp, $20,000).

Achievable timing matters for the SPY comparison: with 15:45 fills and measured spreads CWMR
trails SPY (13.8% against 14.5%); with the one-day delay, tradable at the close with
market-on-close orders, it led SPY before costs (16.2%). Closing-auction costs were not measured,
so whether that lead survives is open.

**Statistics.** Paired Sharpe tests (no rf): CWMR method A against SPY +0.07 (p 0.51), against
CRP +0.17 (p 0.19); with measured spreads against SPY -0.01 (p 0.94), against CRP +0.10
(p 0.47); btest timing with measured spreads against SPY -0.07 (p 0.52). The mean annual return
difference of CWMR (method A) over SPY is +3.0%, 95% confidence interval -1.2% to +7.1%.

**Start-date sensitivity.** CWMR's state builds up from its first day, so its results depend
on the start. Restarted each January, method A, no costs:

| Start | CWMR | CRP | SPY | CWMR with measured spreads |
|---|---|---|---|---|
| 2016 | 17.5% | 12.0% | 14.5% | 15.7% |
| 2017 | 14.6% | 11.8% | 14.7% | 12.8% |
| 2018 | 14.9% | 10.5% | 13.7% | 13.1% |
| 2019 | 15.2% | 13.7% | 17.1% | 13.3% |
| 2020 | 14.9% | 11.1% | 14.5% | 12.8% |
| 2021 | 13.2% | 10.5% | 13.5% | 10.9% |
| 2022 | 5.8% | 5.9% | 8.9% | 3.5% |
| 2023 | 22.6% | 16.1% | 25.6% | 19.5% |

From the 2016 start, CWMR's lead over SPY comes mostly from 2017 (+13.5 points), 2018 (+12.3)
and 2020 (+10.7); it trailed in 2016, 2019, 2022 and 2023.

**Measured spreads** (`spreads.py`): for each session, the median half-spread over every SIP
quote in the minute 15:45:00-15:45:59 New York time; reported value is the median of 45 such
sessions (5 per year 2016-2024, all measured for every ETF): SPY 0.17 bp, QQQ 0.26, IWM 0.30, DIA 0.29, EFA 0.73, EEM 1.20, XLK 0.50, XLF 1.68,
XLV 0.50, XLE 0.74, XLI 0.64, XLY 0.41, XLP 0.80, XLU 0.81, XLB 0.82, XLRE 1.35; equal-weight
average 0.70 bp. Excludes market impact and broker price improvement. These are costs for
trading at 15:45; method A and the one-day delay trade at the close, where a closing-auction
order pays no spread, so for those rows the measured spreads overstate costs.

## 4. Out of sample: NASDAQ-100 stocks, 2016-2024 (`ndx_test.py`)

The authors' functions, method A, Alpaca daily bars adjusted for splits and dividends. Universe:
current NASDAQ-100 members (October 2026 list) with data in 2016-2024, excluding SPCX, whose
ticker belonged to an unrelated fund in that period. This universe is chosen by later success,
so it is illustrative, not a clean test: survivorship and look-ahead in the membership list
inflate every strategy, and the direction of the bias between CRP and the mean-reversion
strategies is unknown.

CAGR (Sharpe no rf):

| | CRP | CWMR 0 bp | CWMR 1 bp | CWMR 3 bp | PAMR 0 bp | PAMR 1 bp | PAMR 3 bp |
|---|---|---|---|---|---|---|---|
| 97 members | 24.1% (1.18) | 31.4% (1.06) | 27.9% (0.96) | 21.0% (0.78) | 27.8% (1.09) | 24.3% (0.98) | 17.6% (0.76) |
| 80 with full history | 25.8% (1.18) | 22.0% (0.95) | 18.5% (0.82) | 11.8% (0.58) | 30.2% (1.14) | 26.6% (1.03) | 19.6% (0.82) |

The 17 members dropped in the second row listed after 2016; the paper's method holds them at a
flat placeholder price until they list. Paired Sharpe tests against CRP: every point estimate is
negative (-0.04 to -0.35), none significant at 5% (smallest p 0.06, CWMR full history at 1 bp).
Turnover 274-291x. Stock spreads were not measured; the return break-even against CRP lies
between 1 and 3 bp for the 97-member set.

## What this supports and what it does not

Supported:

- The paper's numbers are correctly computed from its data and code.
- In-sample (1998-2009), CWMR's and PAMR's returns exceed CRP's after 10 bp costs or a one-day
  delay. CWMR's risk-adjusted advantage is not significant once either friction is applied;
  PAMR's survives the delay (p 0.0002) but not the delay plus 5 bp.
- OLMAR and EG as implemented are CRP; FTRL's reported edge depends on the tickers with
  incomplete data; CWMR and RMR differ from the published algorithms.
- Out of sample (2016-2024) on liquid ETFs, CWMR trails SPY after measured spreads with 15:45
  fills; on current NASDAQ-100 members CWMR and PAMR have lower Sharpe ratios than CRP. None of
  the tested out-of-sample comparisons is statistically significant.

Not supported by this work:

- That the paper's algorithms fail in general. The out-of-sample tests use other assets and the
  paper's parameters, not re-tuned ones.
- Why the effect is smaller after 2016 (period, asset type, data vendor, survivorship and tuning
  all differ between the samples).
- Anything about the roughly 25 algorithms not tested here, including histogram pattern matching
  (about 600x in the paper).
- Whether the 1998-2009 results contain after-hours prints beyond the two bad prints found.
- Whether the one-day-delay lead over SPY on ETFs survives closing-auction costs.

## All paper strategies in btest

Every algorithm in the paper now runs as a btest lab strategy (`strategies/olps/`, library
`src/btest/olps.py`, each port checked against the authors' functions in `tests/test_olps.py`).
On the 16 ETFs, 2016-2024, btest timing, $20,000 (runs 35-42 and 43-70; CAGR at 0 bp / 0.7 bp,
Sharpe T-bill and max drawdown at 0.7 bp):

| Strategy | 0 bp | 0.7 bp | Sharpe | Max DD |
|---|---|---|---|---|
| CWMR (paper's variant) | 16.6% | 13.8% | 0.65 | -35.0% |
| Meta ensemble, exponential weights (FU / OGU) | 13.6% | 12.4% | 0.62 | -37.9% |
| Universal portfolios | 12.3% | 12.3% | 0.65 | -35.0% |
| Aggregation (random base portfolios) | 12.3% | 12.3% | 0.65 | -35.0% |
| Follow the leading history | 13.3% | 12.1% | 0.62 | -34.4% |
| Follow the leader | 12.1% | 12.1% | 0.63 | -34.5% |
| FTRL, EG (smoothing 1.0), aggregation algorithm | 11.9% | 11.9% | 0.62 | -35.8% |
| CRP, monthly | 11.8% | 11.8% | 0.62 | -35.6% |
| RMR | 11.8% | 11.8% | 0.62 | -35.8% |
| Buy and hold, equal weight | 11.5% | 11.5% | 0.63 | -32.5% |
| PAMR (paper's code) | 12.1% | 11.0% | 0.54 | -43.4% |
| Meta ensemble, Newton (ONU) | 12.7% | 10.3% | 0.51 | -36.0% |
| PAMR-1 (Li et al.) | 9.8% | 8.9% | 0.41 | -55.7% |
| Pattern matching (histogram, semi-log-optimal) | 8.9% | 8.3% | 0.42 | -35.0% |
| Anticor | 10.1% | 8.1% | 0.41 | -38.4% |
| OLMAR (Li and Hoi) | 9.2% | 6.9% | 0.31 | -52.4% |

SPY over the same window: 14.5%, Sharpe 0.73. Most follow-the-winner and meta strategies stay
close to equal weights on these ETFs (turnover near 1x a year), so they track CRP. None of these
runs beats SPY after costs.

## Holdout test of monthly CWMR (pre-registered)

Written and committed before running. Hypothesis from the 2016-2024 study
(`outputs/monthly_robustness.out`): the paper's CWMR, learning from daily prices but trading
only at month end, beats SPY after realistic costs.

- Strategy: lab `olps/cwmr_monthly` v1, unchanged (epsilon 0.89, theta 0.92, eta 0.93; 16 ETFs;
  decide 15:30, fill 15:45 on the last session of each month).
- Window: 2025-01-01 to the latest data (sessions through 2026-10-02). btest's holdout; no run
  of any strategy has used it.
- Settings: $20,000, 0.7 bp per dollar traded, fractional shares, idle cash at the T-bill rate,
  benchmark SPY.
- Pass: CAGR and Sharpe ratio both above SPY's over the same window. Also reported: the paired
  Sharpe test against SPY (not expected to be significant over 21 months).
- Run once. Whatever the outcome, the strategy is not modified and rerun on this window.

Result (btest run 73, lab job 77, 438 sessions): **fail.**

| 2025-01-01 to 2026-10-02 | Monthly CWMR | SPY |
|---|---|---|
| CAGR | 18.28% | 18.36% |
| Total return | 34.1% | 34.2% |
| Sharpe (T-bill) | 0.81 | 0.87 |
| Max drawdown | -20.3% | -18.7% |

Paired Sharpe test against SPY: -0.08 (no rf), p 0.77. It beat SPY in 8 of 21 months. Turnover
16x a year. Out of sample, monthly CWMR matched SPY's return with slightly more risk; the
2016-2024 lead (18.3% against SPY's 14.5%) did not carry over.

## Weekly trading instead of monthly, 2016-2024 (`weekly.py`)

Run after the monthly holdout failed. Same 16 ETFs, btest timing, 0.7 bp, SPY 14.5% (Sharpe
0.73). A learns from daily prices and trades on each week's last session; B learns from weekly
bars (each ISO week's last close) and trades on the same day. Full table in
`outputs/weekly.out`.

| CWMR (paper) | CAGR | Sharpe (T-bill) | Turnover | Paired Sharpe vs SPY, p |
|---|---|---|---|---|
| Daily, as published | 13.8% | 0.65 | 349x | |
| A: trade weekly | 14.3% | 0.68 | 78x | -0.07, 0.54 |
| B: weekly bars | 17.6% | 0.81 | 73x | +0.06, 0.64 |
| Monthly, for reference | 18.3% | 0.87 | 18x | +0.13, 0.24 |

B's lead depends on where the weeks end. With 5-session bars at each of the 5 possible offsets,
B returns 9.4% to 13.9% (Sharpe 0.46 to 0.65), and none beats SPY on CAGR and Sharpe. A beats
SPY on both at 1 of 5 offsets. Monthly A beat SPY at 15 of 21 offsets. Weekly trading quadruples
turnover against monthly and does not hold up in-sample, so it was not run on the holdout,
which the monthly test has already used.

## Long-history test of monthly CWMR, 1995-2015 (pre-registered)

Superseded. Every number from `long_history_run.py` in this section (stand-in series, and its
`continuous`, `control` and `validate` runs) decides and fills at the same close; the script
was not rerun after next-open fills were introduced.

Written and committed before running. The 2016-2024 study chose monthly CWMR; this asks whether
its lead over SPY also appears in the 21 years before, which no strategy here has seen.

**Data** (`long_history.py`, check in `outputs/long_history_check.out`). Each of the 16 slots
uses its ETF from launch and a stand-in before, all as daily total returns (Yahoo adjusted
closes, dividends reinvested). No slot is empty at any point, so the universe never changes.

| Slot | Stand-in until ETF launch | ETF from | Daily corr. with ETF, launch-2024 |
|---|---|---|---|
| SPY | none | 1993-01-29 | |
| QQQ | Rydex NASDAQ-100 (RYOCX) | 1999-03-10 | 0.978 |
| IWM | Vanguard Small-Cap Index (NAESX) | 2000-05-26 | 0.981 |
| DIA | Dow price index plus 2% a year (no dividend series found) | 1998-01-20 | 0.987 |
| EFA | 60% Vanguard European (VEURX), 40% Pacific (VPACX) | 2001-08-27 | 0.968 |
| EEM | Vanguard Emerging Markets Index (VEIEX) | 2003-04-14 | 0.938 |
| XLK, XLF, XLV, XLE | Fidelity Select FSPTX, FIDSX, FSPHX, FSENX | 1998-12-22 | 0.949, 0.965, 0.810, 0.970 |
| XLI | Ken French 12-industry "Manuf" (Fidelity's FCYIX has no history on Yahoo) | 1998-12-22 | 0.942 |
| XLY, XLP, XLU, XLB | Fidelity Select FSCPX, FDFAX, FSUTX, FSDPX | 1998-12-22 | 0.933, 0.869, 0.878, 0.939 |
| XLRE | Fidelity Real Estate Investment (FRESX) | 2015-10-08 | 0.971 |

The Fidelity Select funds are actively managed, so they track their sectors loosely (0.81 to
0.97). Most of the window runs on stand-ins: until 1998 every slot but SPY is one.

**Pipeline check** (`long_history_run.py validate`, `outputs/long_history_validate.out`). On
2016-2024, where every slot is the ETF, this data gives monthly CWMR 18.40%, Sharpe 0.87,
turnover 17.8x; btest gave 18.3%, 0.87, 18x. SPY gives 14.58% here, matching the benchmark
column of btest runs (14.5%).

**Test.**

- Strategy: lab `olps/cwmr_monthly` v1, unchanged (epsilon 0.89, theta 0.92, eta 0.93), learning
  from scratch on 1995-01-03.
- Window: 1995-01-03 to 2015-12-31.
- Timing: daily closes only, so it decides on the close of each month's last session and fills
  at that close (btest decides at 15:30 and fills at 15:45; the check above shows they agree).
- Settings: $20,000, fractional shares, idle cash at the 3-month T-bill rate (FRED DTB3),
  benchmark SPY with dividends reinvested.
- Pass: CAGR and Sharpe ratio both above SPY's at 0.7 bp per dollar traded. Also reported: the
  paired Sharpe test, max drawdown, turnover, and results at 5, 10 and 20 bp.
- Limits: the stand-ins are investable but were not tradable this cheaply. Fidelity Select
  funds charged short-term trading fees then, so this tests whether the signal exists in
  these return series, not whether it could have been traded profitably in 1995.
- Run once. Whatever the outcome, the strategy and the data are not changed and rerun on this
  window.

Result (`outputs/long_history.out`, 5,291 sessions): **pass.**

| 1995-01-03 to 2015-12-31, 0.7 bp | Monthly CWMR | SPY |
|---|---|---|
| CAGR | 11.57% | 9.33% |
| Sharpe (T-bill) | 0.54 | 0.43 |
| Max drawdown | -52.2% | -55.2% |
| Turnover | 14.1x | 0x |

Paired Sharpe test against SPY: +0.11 (no rf), p 0.15. Costs: 10.8% at 5 bp, 10.0% at 10 bp,
8.2% at 20 bp, so it falls behind SPY between 10 and 20 bp.

Added after the run, as a check on the stand-ins (`long_history_run.py control`,
`outputs/long_history_control.out`): monthly equal weight in the same 16 slots returned 9.76%,
Sharpe 0.46. CWMR's lead over equal weight is about the same while the stand-ins dominate
(1995-1998: 23.9% against 22.0%) as after the ETFs launch (1999-2015: 8.8% against 7.1%), so
the stand-ins do not explain it. Against equal weight, the paired test gives p 0.33.

Monthly CWMR beat SPY on CAGR and Sharpe in 1995-2015 as it did in 2016-2024, but failed the
2025-2026 holdout. None of the three comparisons is statistically significant on its own.

Run continuously from 1995 to 2024 instead of restarting in 2016 (`long_history_run.py
continuous`, `outputs/long_history_continuous.out`), monthly CWMR returns 11.95% against SPY's
10.82% (Sharpe 0.57 against 0.51, paired p 0.34). Its 2016-2024 part falls to 12.9% against
SPY's 14.4%. Started fresh in 2016, it returned 18.3% over the same years, so the 2016-2024 lead
that selected it depends on starting the algorithm in 2016.

Without stand-ins (btest long-history data, each ETF only from its launch; same-close fills; rerun as runs 84 and 85 from
the website), monthly CWMR returns 7.32% over 1995-2015 against SPY's 9.33%, and 8.60% over
1995-2024 against 10.82%. Until DIA launched it had one symbol and held cash: its first trade
was 1998-01-30, by which time SPY had more than doubled. From 1999-01-04 to 2015-12-31, with the
sector ETFs trading, it grew 2.94x against SPY's 2.25x (6.5% a year against 4.9%).

## CWMR on monthly and weekly bars, 1999-2015 (pre-registered)

All long-history results in this section and the ETF-only paragraph above were first computed
with fills at the decision's own close; the rerun with next-open fills at the end of this section
replaces them.

Written and committed before running. Variant A above learns from daily moves but holds for a
month. These variants judge winners and losers over the same period they hold: B learns from
month-end (or week-end) closes and trades at each month (or week) end. In 2016-2024, monthly
bars returned 11.6% and weekly bars 17.6% against SPY's 14.5%; weekly bars failed the offset
check. Neither has been run before 1999. The 1999-2015 window has been seen only by variant A.

- Strategies: lab `olps/cwmr_monthly_bars` and `olps/cwmr_weekly_bars` v1 (CWMR with epsilon
  0.89, theta 0.92, eta 0.93; the 16 ETFs; bars = "monthly" with rebalance = "month_end", and
  bars = "weekly" with rebalance = "weekly").
- Data: btest long history (Yahoo day bars), each ETF from its first trading day; QQQ joins in
  March 1999, IWM in 2000, EFA in 2001, EEM in 2003, XLRE in October 2015.
- Window: 1999-01-01 to 2015-12-31. Decide and fill at the close; $20,000, 0.7 bp per dollar
  traded, fractional shares, idle cash at the T-bill rate, benchmark SPY with dividends.
- Pass, judged separately for each: CAGR and Sharpe ratio both above SPY's. Also reported: max
  drawdown, turnover.
- Run once each from the website. Whatever the outcome, neither is changed and rerun on this
  window.

Result (same-close fills; rerun as runs 86 and 87): **both pass.**

| 1999-01-01 to 2015-12-31, 0.7 bp | CAGR | Sharpe (T-bill) | Max drawdown | Turnover |
|---|---|---|---|---|
| CWMR, monthly bars | 8.47% | 0.38 | -61.8% | 14.0x |
| CWMR, weekly bars | 11.50% | 0.52 | -48.2% | 79.6x |
| SPY | 4.90% | 0.25 | -55.2% | 0x |

Added after the runs (`bars_1999.py`, `outputs/bars_1999.out`): monthly equal weight in the same
ETFs returned 6.61% (Sharpe 0.33), so holding these ETFs at all beat SPY in this window.

- Monthly bars against equal weight: paired Sharpe +0.04, p 0.65. Its lead over SPY is mostly the
  lead equal weight already has.
- Weekly bars: against SPY, paired Sharpe +0.26, p 0.02; against equal weight, +0.18, p 0.09.
  Two variants were tested, so p 0.02 is about 0.04 after a Bonferroni correction. In 2016-2024
  the same variant failed the offset check (0 of 5 offsets beat SPY).
- Costs: weekly bars falls to 7.86% at 5 bp, 3.78% at 10 bp (below SPY) and -3.91% at 20 bp,
  because it trades 80x its account a year. Monthly bars holds up: 7.13% at 10 bp, 5.72% at 20
  bp. Bid-ask spreads on the sector SPDRs were wider in 1999-2008 than today's 0.7 bp, so the
  weekly result depends on costs this backtest assumes but cannot confirm for those years.

Weekly bars run on from 1999 to 2024 (same-close fills, rerun as run 88; not pre-registered; 2016-2024 was already
seen): 13.32% against SPY's 8.09%, Sharpe 0.60 against 0.40, max drawdown -48.2% against -55.2%,
turnover 76x. It led SPY in each part: 10.5% against 3.5% in 1999-2007, 12.7% against 6.5% in
2008-2015, and 16.8% against 14.4% in 2016-2024.

Does it depend on the week ending on Friday? (`weekly_offsets_longhist.py`,
`outputs/weekly_offsets_longhist.out`.) The same strategy with weeks of 5 sessions ending on each
of the 5 possible days, each run once over 1999-2024 at 0.7 bp:

- 1999-2015: all six versions beat SPY (4.9%) and equal weight (6.6%), at 10.0% to 14.0%.
- 2016-2024: SPY returned 14.4%. The calendar version (16.8%) and one offset (16.0%) beat it; three
  returned 13.8% to 14.1%, and one 11.7%. Only those two beat SPY's Sharpe of 0.73.
- 1999-2024: all six beat SPY (8.1%) and equal weight (8.4%), at 11.4% to 13.9%.

So the lead before 2016 does not depend on the day the week ends. After 2016 the versions roughly
tie SPY, and the calendar version's lead there is the best of six. Every version trades 71x to
76x its account a year, so the cost question above applies to all of them.

At 10 bp per dollar traded (same-close fills, rerun as run 89), the calendar version returns 5.58% a year over
1999-2024 against SPY's 8.09% (Sharpe 0.27 against 0.40): 3.8% against 4.9% in 1999-2015 and
9.1% against 14.4% in 2016-2024. $10,000 grows to $41,023 against SPY's $75,547.

**Adversarial review** (`docs/analysis/2026-10-06-weekly-cwmr-review.md`, four reviewers): the
numbers reproduce, but these runs decide on a close and fill at that same close. With the fill one
session later, weekly bars returns 7.28% over 1999-2015 (equal weight 6.61%, SPY 4.90%), 14.61%
over 2016-2024 (SPY 14.4%) and 9.76% over 1999-2024 (SPY 8.09%). Costs break even against SPY at
about 7 bp; the backtest charges no commissions (243-315 fills a year in 1999-2001 with those same-close
fills; 238-313 with next-open fills, `robustness.py` in the replication repository); and the
portfolio holds a median of 2 ETFs. The result is not evidence of a tradable edge.

**Rerun with next-open fills.** btest's long history now fills each order at the next session's
open (commit a3966b3). Every long-history run was rerun from the website (runs 84-89; the
same-close runs were deleted) and the scripts' outputs regenerated (`bars_1999.out`, `weekly_offsets_longhist.out`).
At 0.7 bp unless stated:

| Run | Strategy, window | Same-close fills | Next-open fills | SPY |
|---|---|---|---|---|
| 84 | Monthly CWMR (daily signal), 1995-2015 | 7.32% | 6.79% | 9.33% |
| 85 | Monthly CWMR (daily signal), 1995-2024 | 8.60% | 8.09% | 10.82% |
| 86 | Monthly bars, 1999-2015 (pre-registered) | 8.47% | 8.90% | 4.90% |
| 87 | Weekly bars, 1999-2015 (pre-registered) | 11.50% | 9.82% | 4.90% |
| 88 | Weekly bars, 1999-2024 | 13.32% | 12.10% | 8.09% |
| 89 | Weekly bars, 1999-2024, 10 bp | 5.58% | 4.46% | 8.09% |

Both pre-registered variants still beat SPY on CAGR and Sharpe over 1999-2015 (Sharpe 0.40 and
0.45 against 0.25), and equal weight in the same ETFs still returns 6.61%. Paired Sharpe tests
for weekly bars: against SPY p 0.11 (was 0.02), against equal weight p 0.33 (was 0.09); for
monthly bars, p 0.17 and 0.52. Weekly bars falls below SPY between 5 bp (6.24% over 1999-2015) and
10 bp (2.23%). Across the six week-end versions, 1999-2015 returns 7.8% to 13.4% (all above SPY
and equal weight) and 2016-2024 returns 11.6% to 16.4% against SPY's 14.4%, with only the calendar
version and one offset above SPY. Weekly bars over 1999-2024 at next-open fills: 9.9% in
1999-2015 and 16.4% in 2016-2024.

## Applications for btest

1. **CRP as a standard baseline.** Monthly CRP (`olps/crp`): 0.3x turnover, 11.8% on the ETFs.
   Use it beside SPY and 60/40 for multi-asset strategies.
2. **Per-symbol costs (plan gap G8).** Results here turn on tenths of a basis point. The measured
   spreads above are a starting table.
3. **Turnover beside Sharpe.** Annual turnover times cost per dollar traded approximates the
   yearly drag (353x times 1 bp is about 3.5%; CWMR measured 17.5% to 13.4%).
4. **Start-date and paired-test reporting.** Stateful strategies need a start-date grid; strategy
   comparisons need paired tests, not single-Sharpe standard errors.
5. **Port carefully from the authors' code.** It is MIT-licensed, but OLMAR, EG, CWMR and RMR
   differ from their sources.

## Corrections

- Long-history runs before commit a3966b3 (the same-close website runs, since deleted, the stand-in research test in
  `long_history.py`, and the first outputs of `bars_1999.py` and `weekly_offsets_longhist.py`)
  filled orders at the close their decision had already seen. Fills are now at the next
  session's open; the long-history results were rerun (runs 84-89). The stand-in test keeps its
  original same-close numbers as the record of what was pre-registered.

- The 2016-2024 studies (`monthly.py`, `monthly_robustness.py`, `weekly.py`) took SPY from
  btest's buy-and-hold strategy, which kept dividends as cash instead of reinvesting them
  (8.6% of the account by the end of 2024). That understated SPY at 13.8% a year against its
  14.5% total return. The strategy now reinvests (lab `baseline/buy_hold` v2), the scripts were
  rerun, and the figures above are corrected: monthly CWMR beats SPY at 15 of 21 trading days,
  not 18, and its paired p is 0.24, not 0.27. The holdout and the main strategy table used the
  run's benchmark column, which was already a total return, so they are unchanged. The
  docstring of `strategies/olps/cwmr_monthly.py` keeps the old figures, because the
  pre-registered holdout test names that code.
- Draft 1 said the paper's data was unavailable and that its headline results "do not survive
  realistic testing". The data is in the authors' repository, the results reproduce, and in the
  paper's own sample they survive costs and delay in return terms.
- Draft 1's btest CWMR rebuilt its state from the last 252 sessions; in a script emulation that
  cut CWMR from 15.8% to 8.6% (2017-2024, btest timing, no costs). The port now replays the full
  history.
- Drafts 1-2 assumed or measured spreads with a script that sampled only the first seconds of the
  minute and skipped rate-limited days; the remeasured average is 0.70 bp.
- Draft 2 compared CWMR with SPY on ETFs and with CRP on stocks, said CWMR beats SPY "only under
  the paper's assumptions" (contradicted by its own delay and measured-spread rows), quoted a
  single-Sharpe standard error for paired comparisons, gave turnover as "130-390x", described
  OLMAR as "never trades", and said two of five follow-the-loser implementations differ (four
  do: OLMAR, CWMR, RMR, and EG among follow-the-winner).
- Account size does not matter: btest runs at $20,000 and $100,000 give identical percentages
  (runs 22-29 and 30-34).

## Review record

Panel: three independent reviewers on draft 2 (sha256 a5e81c0c...): quantitative/statistical
method, code and data audit, hostile-reader logic. Each reran scripts; all reported figures they
checked reproduced. Dispositions:

| Finding | Disposition |
|---|---|
| Paper's data is public; tables reproduce; delay cuts CWMR to 90x | Confirmed (rerun), section 1 added, summary rewritten |
| Benchmark switched between universes | Confirmed, SPY and CRP reported for both |
| "Beats SPY only under the paper's assumptions" contradicts own tables | Confirmed, removed |
| Live-timing break-even 0.03 bp omitted; two live-timing estimates disagree | Confirmed, explained by input definition (section 3) |
| Single-Sharpe SE applied to paired comparisons | Confirmed, paired tests added |
| Start-date dependence | Confirmed (rerun), table added |
| NASDAQ-100 universe design, SPCX ticker reuse | Confirmed, SPCX removed, test labelled illustrative |
| Survivorship "especially flatters loser-buyers" unsupported | Confirmed, removed |
| Three Sharpe conventions unlabelled | Confirmed, every table labelled |
| Turnover "130-390x", two definitions | Confirmed, corrected and defined once |
| Disclosed limitations presented as findings | Confirmed, framed as quantifying section 6.4 |
| EG also reduces to CRP | Confirmed (code and rerun), added |
| FTRL edge from placeholder prices | Confirmed (rerun on 61 full-history tickers) |
| RMR and Anticor deviate from sources | RMR confirmed by reading; Anticor not independently checked, not claimed |
| Two bad prints (PCAR, XRAY) | Confirmed (rerun), added |
| Spread script sampled only first seconds, skipped 429s; XLB/XLU value | Confirmed, remeasured |
| Delay raising PAMR/Anticor returns undermines the "not an artifact" inference | Confirmed, inference withdrawn |
| Published scripts had placeholder paths | Confirmed, fixed and rerun from the repository |
| Sample ends 2009, not 2010 | Confirmed, corrected |
| Draft 3: PAMR's delay advantage untested, summary claimed no friction survives | Confirmed (p 0.0002), tests and summary corrected |
| Draft 3: "beats CRP under every condition, SPY only from 2016" contradicted by tables | Confirmed, rewritten from the tables |
| Draft 3: "achievable timing" ignored the market-on-close delay row | Confirmed, claim scoped to 15:45 fills |
| Draft 3: walk-forward claim not engaged; Anticor alpha inconsistency | Confirmed, section 1 note added |
| Draft 3: FTRL attribution to placeholders not isolated | Confirmed, reworded |
| Draft 3: several numbers printed by no script | Confirmed, scripts now print them (outputs/) |
| Draft 3: correlation range, Exhibit A vs defaults, abstract quote, "four" vs five, 2017 span, 0.3x turnover, spread wording, "none tested" | Confirmed, corrected |

## 2026-10-08: engine fixes and regenerated outputs

A code review before publishing the repository found three fill-timing errors in the
portfolio engine. The scripts' outputs in `outputs/` were regenerated with the fixed engine;
website runs 35-42 and 84-89 in the database still carry the earlier numbers.

- With btest bars, an order for a symbol with no trade between 15:45 and the close filled at
  that day's last trade, which came before the order existed. This happened on 92 early XLRE
  sessions and on 2019-08-12, where the bars have a gap for every symbol. Such orders now do
  not fill.
- On long history, a trade filled at the next session's open was booked on the decision day
  and valued at that day's close, so every rebalance day's return included the following
  night's gap. Orders now execute at the start of the next session.
- On long history, a decision on a run's last session filled at that session's close, the
  price it decided on. It is now dropped.

The Sharpe ratio's denominator is now the standard deviation of excess returns rather than of
raw returns (`btest.metrics`).

Effect on the numbers quoted above. 2016-2024, 16 ETFs, daily CWMR: 16.0% at 0 bp (was
16.6%), 14.2% at 0.43 bp (was 14.9%; now below SPY's 14.5%), 13.2% at 0.70 bp (was 13.8%).
CWMR with a daily signal traded monthly is unchanged at 18.3%; Anticor traded that way 16.8%
(was 17.0%).
1999-2015 on long history: weekly bars 9.82% and monthly bars 8.90% are unchanged; equal
weight 6.59% (was 6.61%); weekly bars' paired Sharpe test against SPY p 0.09 (was 0.11),
against equal weight p 0.30 (was 0.33). No verdict in the regenerated outputs changes. Runs 84-85
(monthly CWMR on long history) were recomputed by `paper_sections_4_5.py`: 6.80% over 1995-2015
(was 6.79%), 11.18% over the 2016-2024 part (unchanged). The holdout run 73 was not rerun: no
2025-2026 session lacks a fill bar, and its Sharpe ratios recomputed from the stored equity are
unchanged (0.81 and 0.87). The working paper was revised with these numbers on 2026-10-08. Full diffs: `git log -p -- docs/research/olps-replication/outputs/`.

## 2026-10-08: the paper reports 1999-2024 throughout

The working paper now reports every ETF result over one window, 1999-2024, on long-history
daily data (decide on the close, fill at the next open), instead of separate 1999-2015 and
2016-2024 tables and the 2016-2024 minute-data sections. The registered 1999-2015 results and the
holdout are stated as such. Sources: the replication repository's `etf_tables.py`,
`robustness.py` and `autocorrelation.py`, cross-checked by `paper_1999_2024.py` here (identical
to the digit). New finding on this window: daily CWMR returns 12.13% at 0.7 bp against equal
weight's 8.37% and SPY's 8.09% (170x turnover, break-even 2.2 bp against equal weight), while the
monthly daily-signal variant chosen for the holdout returns 7.72%. No Sharpe difference is
significant after a Holm correction over the nine comparisons (smallest 0.11).
