# Paper review: "Online Quantitative Trading Strategies" (Lahanis, Liu, Zhou, NYU Stern)

Draft 3, October 5, 2026. Supersedes drafts 1 (commit 4f1fa05) and 2 (unpublished), whose
central claims were wrong; see "Corrections". Draft 2 was reviewed by three independent
reviewers before this rewrite; their findings and what was done with each are listed under
"Review record".

Sources: `Glucksman_Lahanis.pdf` (20 pages, Glucksman Fellowship, May 2025); the authors' code
and data, [nglahani/Online-Quantitative-Trading-Strategies](https://github.com/nglahani/Online-Quantitative-Trading-Strategies)
at commit `7c2e88d` (MIT license). Every number below comes from a script in
`docs/research/olps-replication/` (setup in its README); the raw outputs are in
`docs/research/olps-replication/outputs/`.

## Summary

1. **The paper's results reproduce exactly from the authors' published data and code.** Their
   repository contains the price data (93 NASDAQ-100 stocks, 1998-01-02 to 2009-12-31). Running
   their functions gives CWMR 1590.38, PAMR 788.26, Anticor 36.89, FTRL 15.25, CRP 12.16,
   buy-and-hold 9.17, matching Tables 3 and 4 to the reported decimals.
2. **In that sample, mean reversion survives costs and delay in return terms, not in
   risk-adjusted terms.** CWMR still compounds 43.6% a year at 10 bp per dollar traded and 45.6%
   with a one-day trading delay, against 23.2% for an equal-weight portfolio rebalanced daily
   (CRP). Its Sharpe ratio advantage over CRP is significant without frictions (p < 0.0001) but
   not at 10 bp (p = 0.29) or with the delay (p = 0.11). The parameters were tuned on this same
   sample, so it is in-sample evidence.
3. **Out of sample (2016-2024) the effect is small or absent.** On 16 liquid equity ETFs, CWMR
   beats CRP under every cost and timing tested but beats SPY only from a 2016 start and before
   costs; with measured spreads and trade timing a live system can achieve it trails SPY. On
   current NASDAQ-100 members it has a lower Sharpe ratio than CRP at every cost level,
   including zero. None of the 2016-2024 differences against SPY or CRP is statistically
   significant.
4. **Four of the paper's reported strategies are not the algorithms they are named after.**
   OLMAR and EG never change their target weights, so both are CRP (the paper's tables show
   identical numbers). FTRL's edge over CRP comes from tickers padded with flat placeholder
   prices before they list. CWMR and RMR are modified versions of the published methods.

The paper discloses that it ignores trading costs and that 1998-2010 may not represent recent
markets (section 6.4). Points 2 and 3 quantify those two disclosed limitations; they sit uneasily
with the abstract's claim of performance "under realistic market conditions".

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
  strategies over the same days; it accounts for their correlation (0.92-0.95 here).

## 1. The paper's own sample, 1998-2009 (`paper_data.py`)

93 tickers, 3,019 days. Parameters are the paper's (Exhibit A, equal to the code defaults).

CAGR (wealth multiple), Sharpe rf 5% / no rf:

| Strategy | Method A | A + 1 bp | A + 5 bp | A + 10 bp | One-day delay |
|---|---|---|---|---|---|
| CRP | 23.2% (12.2x), 0.76 / 0.95 | 23.1% | 22.9% | 22.6% | 23.2% |
| CWMR | 85.0% (1,590x), 1.75 / 1.88 | 80.4% (1,174x) | 63.0% (349x) | 43.6% (76x), 1.05 / 1.18 | 45.6% (90x), 1.13 / 1.28 |
| PAMR | 74.5% (788x), 1.63 / 1.77 | 70.1% | 53.5% | 35.1% (37x), 0.90 / 1.04 | 51.9% (149x), 1.26 / 1.41 |
| Anticor | 35.1% (37x), 1.02 / 1.19 | 31.8% | 19.0% | 4.8% (1.8x) | 30.0% (23x) |
| FTRL | 25.5% (15.2x), 1.04 / 1.30 | 25.5% | 25.3% | 25.0% | 25.5% |

Paired Sharpe tests against CRP (annualized difference, no rf): CWMR method A +0.94 (z 4.25,
p < 0.0001); CWMR + 10 bp +0.23 (p 0.29); CWMR one-day delay +0.33 (p 0.11); PAMR + 10 bp +0.09
(p 0.52).

Robustness checks on the same data:

- **Two suspected bad prints.** PCAR on 2000-02-16/17 (price ratio 0.536 then 1.943) and XRAY on
  2004-07-22/23 (0.468 then 2.087) are the only spike-and-reverse pairs beyond 0.6/1.6. Setting
  both to 1.0 lowers CWMR from 1,590x to 1,120x (79.7% a year) and PAMR from 788x to 626x.
- **Tickers with data over almost the whole sample (61).** CWMR method A 85.9% a year; one-day
  delay 30.8%; CRP 21.4%. FTRL falls to 17.2%, below CRP.

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
3. **FTRL's edge comes from placeholder prices.** Before a ticker lists, the code fills its
   price ratios with 1.0 (a flat price). On all 93 tickers FTRL returns 25.5% against CRP's
   23.2%; on the 61 tickers with near-complete data it returns 17.2% against 21.4%. Our code
   audit found FTRL overweights placeholder cells; we did not trace the mechanism further.
4. **CWMR is a modified algorithm.** The docstring calls it "a simplified version of CWMR with
   an additional learning rate factor." The step size is a passive-aggressive closed form
   without Li et al.'s confidence term, the confidence parameter enters the covariance update
   directly, a learning-rate factor is added, and the mean-centering of the update is omitted.
5. **RMR is modified.** It takes the L1-median of past price ratios divided by the last price
   ratio; Huang et al.'s RMR takes the L1-median of past prices divided by the current price.
6. **Missing prices are forward-filled.** A ticker with no data on a day keeps its last price
   (ratio 1.0). In the paper's data, 20 tickers have long runs of placeholder ratios before
   listing, and five stop trading during the sample (APCC, BGEN, MEDI, NXTL, SEBL, all
   acquisitions, so their last prices are close to deal prices).
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

Break-even flat cost against SPY on CAGR: 0.74 bp per dollar traded (method A); 0.43 bp (btest
timing). Measured spreads average 0.70 bp.

Input note: CWMR's result depends on how the day's price ratio is defined. Using 15:14 prices
for every day gives 14.7%; using closing prices for past days and the 15:14 price for the
current day (what a live system sees, and what btest's engine uses) gives 16.3%.

PAMR (authors' code): method A 13.2%; + measured spreads 12.0%; one-day delay 14.3%. Anticor:
method A 10.0%; + measured spreads 7.9%; one-day delay 14.9%.

The one-day delay raises PAMR's and Anticor's returns rather than lowering them, which is not
what a one-day reversal effect predicts; we read the delay results as noise rather than
evidence about the mechanism.

**btest engine** (`strategies/olps/cwmr.py`, a port matching the authors' `cwmr()` to within
7e-9 per weight on the paper's data; full-history replay checked identical to a cached
incremental update): CWMR
16.6% at 0 bp, 14.9% at 0.43 bp, 13.8% at 0.70 bp (Sharpe T-bill 0.77, 0.70, 0.65; SPY 14.5%,
0.73). PAMR 8.9%, OLMAR (Li and Hoi's published form, our implementation) 6.9% and monthly CRP
11.8% at 0.70 bp. Saved as btest runs 35-42 (each strategy at 0 and 0.7 bp, $20,000).

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

**Measured spreads** (`spreads.py`): median half-spread over every SIP quote in the minute
15:45:00-15:45:59 New York time, 5 sessions per year 2016-2024 (45 sessions, all measured for
every ETF): SPY 0.17 bp, QQQ 0.26, IWM 0.30, DIA 0.29, EFA 0.73, EEM 1.20, XLK 0.50, XLF 1.68,
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
  delay, but their risk-adjusted advantage is not statistically significant once either friction
  is applied.
- OLMAR and EG as implemented are CRP; FTRL's reported edge depends on placeholder prices; CWMR
  and RMR differ from the published algorithms.
- Out of sample (2016-2024) on liquid ETFs, CWMR does not beat SPY after measured costs at
  achievable timing, and on current NASDAQ-100 members CWMR and PAMR show no Sharpe advantage
  over CRP; none of these out-of-sample differences is statistically significant.

Not supported by this work:

- That the paper's algorithms fail in general. The out-of-sample tests use other assets and the
  paper's parameters, not re-tuned ones.
- Why the effect is smaller after 2016 (period, asset type, data vendor, survivorship and tuning
  all differ between the samples).
- Anything about the roughly 25 algorithms not tested here, including histogram pattern matching
  (about 600x in the paper).
- Whether the 1998-2009 results contain after-hours prints beyond the two bad prints found.

## Applications for btest

1. **CRP as a standard baseline.** Monthly CRP (`olps/crp`): 0.4x turnover, 11.8% on the ETFs.
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

- Draft 1 said the paper's data was unavailable and that its headline results "do not survive
  realistic testing". The data is in the authors' repository, the results reproduce, and in the
  paper's own sample they survive costs and delay in return terms.
- Draft 1's btest CWMR rebuilt its state from the last 252 sessions; in a script emulation that
  cut CWMR from 15.8% to 8.6% (2016-2024, btest timing, no costs). The port now replays the full
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
