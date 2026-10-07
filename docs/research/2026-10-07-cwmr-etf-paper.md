# Mean-reversion portfolio selection on US-listed ETFs, 1999-2026: a replication with pre-registered tests

[Author name]. October 7, 2026. Working paper.

## Abstract

Lahanis, Liu and Zhou (2025) report that online portfolio selection algorithms built on mean
reversion, CWMR and PAMR among them, earn large risk-adjusted returns on NASDAQ-100 stocks over
1998-2009. We reproduce their tables exactly from their published code and data, then test the
strongest algorithm, the authors' variant of Confidence-Weighted Mean Reversion (CWMR), on 16
liquid US-listed equity ETFs with realistic trading. Daily CWMR trades about 350 times its
account a year and trails SPY at measured 2016-2024 spreads. We searched variants that trade
less, selected one on 2016-2024 data and tested it on data it had not seen. A monthly variant
selected this way tied SPY on a pre-registered 2025-2026 holdout (18.28% against 18.36% a year).
Variants that learn from weekly or monthly bars passed a pre-registered 1999-2015 test against
SPY: weekly bars returned 9.82% a year against SPY's 4.90%. That test turned out to be weak. An
equal-weight portfolio of the same ETFs returned 6.61%, and the strategy's lead over it is not
statistically significant (p 0.33). The lead also disappears at trading costs between 5 and 10
basis points per dollar traded. Before 2001 the minimum tick alone cost more than that on sector
ETFs, and we have no measured spreads for 2001-2010. We find no tradable edge. We also report three errors in our own pipeline that inflated earlier results,
and how we found them.

## 1. Introduction

Online portfolio selection treats investing as a repeated game. Each period an algorithm holds a
portfolio, observes the period's price changes and updates its weights by a fixed rule. Cover
(1991) showed that some rules provably approach the best constant-weight portfolio in
hindsight. A later family of algorithms bets on reversal instead. Anticor (Borodin, El-Yaniv and
Gogan, 2004), PAMR (Li et al., 2012), CWMR (Li et al., 2013) and RMR (Huang et al., 2013) move
weight from recent winners to recent losers. On the historical datasets in this literature
these algorithms report wealth multiples in the hundreds or thousands (Li and Hoi, 2014).

Lahanis, Liu and Zhou (2025) implement about 25 of these algorithms and test them on NASDAQ-100
stocks from 1998 to 2009. Their best result, CWMR, multiplies wealth 1,590 times. They disclose
that they ignore trading costs and that the period may not represent recent markets.

This paper asks whether any version of their CWMR survives realistic trading on instruments a
retail investor can buy today. We use btest, a backtester that trades the way its live system
does, and we pre-register each confirmatory test before running it. Section 2 describes the
data and methods. Section 3 reproduces the original paper. Sections 4 to 6 report the
out-of-sample tests in the order we ran them, since the order matters for how much each result
can be trusted. Section 7 lists errors we found in our own work. Section 8 discusses what the
evidence supports.

## 2. Data and methods

### 2.1 Algorithms

All tests use the authors' CWMR as written in their repository (commit 7c2e88d), ported to btest
and checked against their function to within 7.1e-9 per weight on their data. Their CWMR
differs from the published algorithm of Li et al. (2013). The step size has no confidence term,
a learning-rate factor eta is added and the update is not mean-centred. We keep their parameters
throughout (epsilon 0.89, theta 0.92, eta 0.93) and never re-tune them.

Each period the algorithm receives a vector x of price ratios, one per asset (1.02 means up 2%).
If the portfolio's growth b·x exceeds epsilon, it moves the mean weight vector against x, scaled
by a covariance matrix Σ, and projects the result back to non-negative weights that sum to one.
It then shrinks Σ in the direction of x. Because epsilon is 0.89, the update fires unless the
portfolio falls more than 11% in one period, so in practice it fires every period.

We test four schedules:

| Name | Learns from | Trades |
|---|---|---|
| Daily | daily ratios | every session |
| Monthly, daily signal | daily ratios | last session of each month |
| Monthly bars | month-end to month-end ratios | last session of each month |
| Weekly bars | week-end to week-end ratios | last session of each ISO week |

### 2.2 Universe and data

The universe is 16 ETFs: SPY, QQQ, IWM, DIA, EFA, EEM and ten Select Sector SPDRs (XLK, XLF, XLV,
XLE, XLI, XLY, XLP, XLU, XLB, XLRE). EFA and EEM hold non-US stocks and XLRE holds real estate.
The ETFs launched between 1993 and 2015, so the universe grows over time. In January 1999 it has
11 members and reaches 16 in October 2015. A fund joins on its first trading day. Before that it
holds no weight, and the algorithm keeps what it has learned about the others (section 7.2).

We use two price sources. From 2016 on, btest uses Alpaca SIP minute bars, adjusted for splits
and dividends. A strategy decides at 15:30 New York time on data through 15:14 and fills at
15:45, which is how the live system trades. Before 2016, and for continuous runs from 1999, we
use Yahoo daily bars adjusted for dividends and splits. A strategy decides on a session's close
and fills at the next session's open. We matched the stored Yahoo closes to a fresh download to
within a ratio of 3e-6 on every date.

### 2.3 Costs and benchmarks

Every dollar traded pays a flat cost in basis points (bp), plus the SEC fee on sales. We measured
half-spreads at 15:45 from Alpaca quotes on 45 sessions in 2016-2024:

| ETF | Half-spread (bp) |
|---|---|
| SPY | 0.17 |
| QQQ, IWM, DIA | 0.26 to 0.30 |
| Most sector SPDRs, EFA | 0.41 to 0.82 |
| EEM, XLRE, XLF | 1.20 to 1.68 |
| Equal-weight average | 0.70 |

We charge 0.7 bp unless stated and report results at 5, 10 and 20 bp. The model has no
commissions, no market impact and no taxes. Section 8 discusses each.

The benchmarks are SPY with dividends reinvested and an equal-weight portfolio of the same ETFs,
reset at each month end. The second matters more. A strategy that beats SPY only because these
ETFs beat SPY has learned nothing.

### 2.4 Statistics and procedure

We compare Sharpe ratios with the Jobson and Korkie (1981) test with Memmel's (2003) correction,
on daily returns of two strategies over the same days. The test uses their correlation, 0.71 to
0.95 across this study, so it can detect smaller differences than comparing two independent
estimates. It assumes independent returns. The daily return differences have negative
first-order autocorrelation, which makes the test conservative. In the cases one reviewer
checked with a block bootstrap, before the timing correction of section 7.3, the bootstrap gave
smaller p-values than the test.

Each confirmatory test was written into the research log and committed to git before it ran.
The commit names the strategy version, window, settings and pass criterion, and states that the
strategy will not be changed and rerun on that window. Each commit precedes its run. The
holdout's commit, for example, is 28 seconds older than the run's database record. We kept 2025-01-01 onward as a holdout and have used it once.

## 3. Reproducing the original paper

The authors' repository contains their data, 93 NASDAQ-100 stocks from 1998-01-02 to 2009-12-31.
Running their functions reproduces their Tables 3 and 4 exactly: CWMR 1,590.38x, PAMR 788.26x,
Anticor 36.89x, FTRL 15.25x and the equal-weight constant rebalanced portfolio (CRP) 12.16x.

The paper's parameters were chosen on this same sample, so these are in-sample results. Within
the sample, mean reversion keeps much of its return under frictions:

| 1998-2009, authors' data | CAGR | Paired Sharpe vs CRP, p |
|---|---|---|
| CRP | 23.2% | |
| CWMR | 85.0% | < 0.0001 |
| CWMR, 10 bp | 43.6% | 0.29 |
| CWMR, one-day delay | 45.6% | 0.11 |
| PAMR, one-day delay | 51.9% | 0.0002 |
| PAMR, one-day delay and 5 bp | 33.9% | 0.49 |

Five of the paper's strategies differ from the algorithms they are named after. As implemented,
OLMAR and exponential gradient never change their target weights. Both reduce to CRP, and the
paper reports identical numbers for all three. FTRL's lead over CRP disappears when the 32
tickers with incomplete data are removed. CWMR and RMR are modified versions of the published
methods. Two bad prints, PCAR in February 2000 and XRAY in July 2004, account for about 30% of
CWMR's final wealth.

## 4. Daily trading, 2016-2024

On the 16 ETFs with btest's live timing, daily CWMR returns 16.6% a year before costs and 13.8%
at 0.7 bp, against SPY's 14.5%. It turns over about 350 times its account a year, so each basis
point of cost removes about 3.5 percentage points of annual return. Its break-even cost against
SPY lies between 0.43 and 0.70 bp. Paired tests against SPY are not significant at any setting we
tested (p 0.51 for the paper's close-to-close timing before costs). Daily CWMR is not worth pursuing at retail costs, and the remaining
sections test schedules that trade less.

## 5. Selecting a lower-turnover variant, and the holdout

We ran all 13 of the paper's strategy families three ways on 2016-2024: daily, daily signal with
monthly trades, and monthly bars. CWMR with a daily signal and monthly trades did best, 18.3% a
year (Sharpe 0.87) against SPY's 14.5% (0.73), with turnover cut to 18x. Its paired p against
SPY was 0.24, and it was the best of about 26 variants, so we treated it as a hypothesis and
pre-registered a test on the untouched 2025-2026 holdout.

It tied SPY:

| 2025-01-01 to 2026-10-02 | Monthly CWMR | SPY |
|---|---|---|
| CAGR | 18.28% | 18.36% |
| Sharpe (T-bill) | 0.81 | 0.87 |
| Max drawdown | -20.3% | -18.7% |

Paired p was 0.77, and it beat SPY in 8 of 21 months. A later continuous run showed why the
2016-2024 result was misleading. The 18.3% depends on starting the algorithm fresh in January
2016. Run on daily ETF data from 1995 with its state carried forward, the same strategy returns
11.2% over 2016-2024 against SPY's 14.4%.

## 6. Learning from weekly and monthly bars, 1999-2024

The monthly variant above learns from daily moves but holds for a month. Short-horizon reversal
in stock returns is documented over weeks (Lehmann, 1990) and a month (Jegadeesh, 1990), so a
signal built from one day's moves and held for a month measures one horizon and bets on
another. Variants that learn from week-end or month-end prices fix that mismatch. Over
2016-2024 they returned 17.6% (weekly bars) and 11.6% (monthly bars) against SPY's 14.5%.
Neither had been run before 1999.

### 6.1 Pre-registered test, 1999-2015

We pre-registered both variants on 1999-2015 with ETF-only daily data. The pass criterion was
CAGR and Sharpe ratio above SPY's at 0.7 bp. This period contains two crashes, and SPY returned
only 4.9% a year.

| 1999-2015, 0.7 bp | CAGR | Sharpe | Max drawdown | Turnover | vs SPY, p | vs equal weight, p |
|---|---|---|---|---|---|---|
| Weekly bars | 9.82% | 0.45 | -50.1% | 79x | 0.11 | 0.33 |
| Monthly bars | 8.90% | 0.40 | -61.4% | 14x | 0.17 | 0.52 |
| Equal weight | 6.61% | 0.33 | -54.4% | 0.3x | 0.10 | |
| SPY | 4.90% | 0.25 | -55.2% | 0x | | |

Both variants pass the criterion as written. But equal weight also passes it, and the paired
tests cannot separate either variant from equal weight. In hindsight the criterion was too easy.
We already knew this basket of ETFs had beaten SPY over this window when we wrote it, so
equal weight was the right benchmark to name.

### 6.2 Robustness to the day the week ends

Weekly bars end on Friday. We reran the strategy with 5-session blocks ending on each of the
other four weekdays. Each version ran once over 1999-2024:

| 0.7 bp | 1999-2015 | 2016-2024 | 1999-2024 |
|---|---|---|---|
| Calendar weeks (Friday) | 9.9% | 16.4% | 12.1% |
| Five shifted versions | 7.8% to 13.4% | 11.6% to 14.8% | 9.6% to 13.5% |
| Equal weight | 6.6% | 11.8% | 8.4% |
| SPY | 4.9% | 14.4% | 8.1% |

Before 2016 every version beats both benchmarks. After 2016 only the Friday version and one
shifted version beat SPY. Over the whole window the Friday version is the second best of six,
and its 2016-2024 result is the best, which is what selection on 2016-2024 would produce.

### 6.3 Costs

At about 76x turnover, each basis point of cost removes about 0.8 percentage points a year.

| Weekly bars | 0.7 bp | 5 bp | 10 bp | 20 bp | SPY |
|---|---|---|---|---|---|
| 1999-2015 | 9.82% | 6.24% | 2.23% | -5.35% | 4.90% |
| 1999-2024 | 12.10% | | 4.46% | | 8.09% |

The break-even against SPY is about 6-7 bp over 1999-2015 and about 5-6 bp over 1999-2024. Before
April 2001 US stocks traded in sixteenths of a dollar, so the smallest possible half-spread on a
$30 sector SPDR was about 10 bp. We found no measured spreads for these ETFs in 1999-2005 and
cannot say when they fell below 5 bp. Over 1999-2001 the strategy also made 243 to 315 trades a
year. At the 1999 average online commission of about $16 a trade, that is about a fifth of a
$20,000 account each year.

## 7. Errors in our own pipeline

Three errors inflated results during this study. We report them because each one changed a
conclusion we had already written down.

### 7.1 A benchmark that did not reinvest dividends

btest's buy-and-hold SPY strategy held dividends as cash. By the end of 2024 cash was 8.6% of the
account, and SPY's 2016-2024 return showed as 13.8% instead of its 14.5% total return. Every
comparison against that baseline overstated the strategy's lead by about 0.7 points a year. The
monthly variant's count of trading-day offsets that beat SPY fell from 18 of 21 to 15 of 21 once
fixed. The holdout test was unaffected, because it used a benchmark built from adjusted closes.

### 7.2 Stand-in funds under ETF names

Our first 1995-2015 test filled the years before each ETF's launch with a similar mutual fund or
index, for example the Rydex NASDAQ-100 fund before QQQ. The motivation was a flaw in our code.
When a new fund appeared, the algorithm discarded its learned state and restarted. We fixed the
restart: a fund not yet trading now gets the average price ratio of those that are, and its
weight goes to them in equal parts, which gives the same portfolio return. We then dropped the
stand-ins, since each ETF should be only itself. With real ETFs only, monthly CWMR returns 6.79%
over 1995-2015 against SPY's 9.33%, because before 1998 it had only SPY to hold and sat in cash.

### 7.3 Filling at the price the decision saw

Our daily-bar data first decided on a session's close and filled at that same close. No one can
trade at a closing price after seeing it. An adversarial review with four independent reviewers
found this, and fills now happen at the next session's open. The correction lowered weekly bars
from 11.50% to 9.82% over 1999-2015 and raised its paired p against SPY from 0.02 to 0.11. Before
the fix, the variant looked significant against SPY. After it, it does not.

Two smaller items from the same review: the reviewers counted about 100 configurations tried
across the whole study, and the strategy holds a median of 2 ETFs after rebalancing. One ETF
carries 90% or more of the account in 36% of weeks.

## 8. Discussion

The original paper's results are real, in the sense that its code computes them correctly from
its data. They do not survive the move to instruments and costs a retail investor faces today.
Every schedule we tried either trails SPY at measured costs (daily), ties it out of sample
(monthly, on the holdout), or beats SPY by roughly as much as an equal-weight portfolio of the
same ETFs does (weekly and monthly bars, 1999-2015).

The weekly-bars variant is the most interesting result. Before 2016 it beat both benchmarks at
every week-end offset. Several explanations fit. Weekly reversal across sector ETFs may have been
real in a market with wider spreads and slower arbitrage, in which case the profit belonged to
whoever supplied liquidity and was not available to someone paying the spread. Pre-2016 daily
closes show negative next-day autocorrelation in excess returns, about -0.05 to -0.09, against
roughly zero after 2016, as measured by one of the reviewers. That pattern fits bid-ask bounce in closing prints, which a backtest
captures and a trader pays for. And the variant came out of a search over many configurations,
which inflates the best result. We cannot separate these with the data we have. Each predicts
the effect fades as markets become cheaper to trade, and after 2016 it roughly ties SPY.

What we would need before calling it an edge:

1. Measured spreads for these ETFs in 1999-2010, to replace the flat cost.
2. A pre-registered test against equal weight, not SPY, on data no variant has touched. The
   2025 holdout has been used once. Data from 2027 on would be clean.
3. Results after commissions for a stated account size, and after tax for taxable accounts. At
   76x turnover almost every gain is short-term.

## 9. Conclusion

We reproduced a published set of mean-reversion results exactly, then lost them to costs, to
timing and to the benchmark. A weekly variant passed a pre-registered test against SPY, but the
test was weak: an equal-weight portfolio of the same ETFs passes it too, and the variant's edge
disappears at costs these ETFs carried twenty years ago. We find no evidence of a tradable edge
for this family of strategies on liquid US-listed ETFs. The three errors in section 7 each made
a strategy look better than it was. Pre-registration plus an independent review caught them.
Single backtests did not.

## Reproducibility

Code and outputs are in the btest repository. The research log is
`docs/research/2026-10-04-online-portfolio-selection-paper.md`, and the review with every
finding and its disposition is `docs/analysis/2026-10-06-weekly-cwmr-review.md`. Scripts and
their saved outputs are in `docs/research/olps-replication/`. The runs behind tables 6.1 and 6.3
are btest runs 86 to 89, made from the lab with strategy files `strategies/olps/cwmr_*.py`.
Pre-registrations are git commits 7f9a8b0 (holdout), d9a912d (1995-2015, stand-in data) and
97b0d4a (1999-2015 bars). The long-history data loader is `src/btest/longhist.py`
(`btest longhist`).

## Acknowledgments

Analysis code, backtests, the adversarial review and drafts of this paper were produced with
Claude (Anthropic) under the author's direction. The author chose the questions, the
pre-registration rules and the corrections.

## References

Borodin, A., El-Yaniv, R. and Gogan, V. (2004). Can we learn to beat the best stock? Journal of
Artificial Intelligence Research 21, 579-594.

Cover, T. M. (1991). Universal portfolios. Mathematical Finance 1(1), 1-29.

Harvey, C. R., Liu, Y. and Zhu, H. (2016). ...and the cross-section of expected returns. Review
of Financial Studies 29(1), 5-68.

Huang, D., Zhou, J., Li, B., Hoi, S. C. H. and Zhou, S. (2013). Robust median reversion strategy
for on-line portfolio selection. Proceedings of IJCAI 2013.

Jegadeesh, N. (1990). Evidence of predictable behavior of security returns. Journal of Finance
45(3), 881-898.

Jobson, J. D. and Korkie, B. M. (1981). Performance hypothesis testing with the Sharpe and
Treynor measures. Journal of Finance 36(4), 889-908.

Lahanis, N., Liu, A. and Zhou, Z. (2025). Online quantitative trading strategies: an empirical
performance overview through backtesting. Glucksman Fellowship, NYU Stern. Code: github.com/nglahani/Online-Quantitative-Trading-Strategies.

Lehmann, B. N. (1990). Fads, martingales, and market efficiency. Quarterly Journal of Economics
105(1), 1-28.

Li, B. and Hoi, S. C. H. (2014). Online portfolio selection: a survey. ACM Computing Surveys
46(3), 35.

Li, B., Hoi, S. C. H., Zhao, P. and Gopalkrishnan, V. (2013). Confidence weighted mean reversion
strategy for online portfolio selection. ACM Transactions on Knowledge Discovery from Data 7(1),
4.

Li, B., Zhao, P., Hoi, S. C. H. and Gopalkrishnan, V. (2012). PAMR: passive aggressive mean
reversion strategy for portfolio selection. Machine Learning 87(2), 221-258.

Memmel, C. (2003). Performance hypothesis testing with the Sharpe ratio. Finance Letters 1(1),
21-23.
