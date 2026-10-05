# Paper review: "Online Quantitative Trading Strategies" (Lahanis, Liu, Zhou, NYU Stern)

October 4, 2026. Source: `Glucksman_Lahanis.pdf` (20 pages, Glucksman Fellowship, May 2025) and
the authors' code, [nglahani/Online-Quantitative-Trading-Strategies](https://github.com/nglahani/Online-Quantitative-Trading-Strategies)
(MIT license). Our replication runs are 22-29 on the btest site.

## Verdict

The paper's headline results (CWMR turning $1 into $1,590 and PAMR into $788 over 1998-2010)
do not survive realistic testing. Run in btest on 17 equity ETFs over 2016-2024, with live
timing and with trading costs set to zero, the best of its mean-reversion strategies returned
12.4% a year against SPY's 14.5%. At 1 basis point per trade they returned 4-8.5%, because they
trade 127 to 393 times the account's value every year.

One idea from the paper holds up, cheaply: a constant rebalanced portfolio (equal weights,
reset monthly) returned 11.9% with almost no trading. It still trailed SPY in this bull market,
which is the honest result.

## What the paper does

The paper studies online portfolio selection: algorithms that pick portfolio weights every day
from past prices and update them as each day's prices arrive. It reimplements about 30
algorithms from Li and Hoi's survey ([ACM Computing Surveys 2014](https://arxiv.org/abs/1212.2129))
in Python and backtests them on NASDAQ-100 stocks, 1998-2010, rebalancing daily at the close.

| Family | Idea | Algorithms tested |
|---|---|---|
| Benchmarks | Reference points | Buy and hold, best stock, constant rebalanced portfolio (CRP) |
| Follow the winner | Put more money in what has been rising | Universal portfolios, exponential gradient, follow the leader, follow the regularized leader (FTRL), aggregation |
| Follow the loser | Put more money in what just fell, expecting a rebound | Anticor, PAMR, CWMR, OLMAR, RMR |
| Pattern matching | Find past days that looked like today and copy what worked after them | Histogram, kernel, nearest-neighbour and correlation selection, each with log-optimal, semi-log-optimal or Markowitz weighting |
| Meta-learning | Run several algorithms and shift money toward whichever is doing best | Aggregation algorithm, fast universalization, online gradient and Newton updates, follow the leading history |

Parameters were chosen by grid search for the highest Sharpe ratio, with a rolling walk-forward
check inside the same 1998-2010 data.

### Reported results (final wealth from $1, Sharpe, max drawdown)

| Strategy | Wealth | Sharpe | Max drawdown |
|---|---|---|---|
| CWMR | 1,590 | 1.75 | -51% |
| PAMR | 788 | 1.63 | -47% |
| Histogram pattern matching | 578-610 | 1.15 | -76% |
| Online gradient update (ensemble of CWMR, FTRL, PAMR) | 66 | 1.26 | -45% |
| Anticor | 37 | 1.02 | -40% |
| FTRL | 15.2 | 1.04 | -42% |
| CRP | 12.2 | 0.76 | -45% |
| Buy and hold | 9.2 | 0.58 | -68% |

The authors conclude that confidence-weighted mean reversion (CWMR, PAMR), regularized momentum
(FTRL), and ensembles of them deliver the best risk-adjusted returns, at a high computing cost
for pattern matching and ensembles.

## Problems found

From the paper:

1. **No trading costs.** The paper says so (section 6.4). The winners rebalance most of the
   portfolio every day, so costs dominate their real results (see our runs below).
2. **Trades at the same close the signal used.** Weights computed from a day's close earn the
   next day's close-to-close return, with no delay between seeing a price and trading on it.
3. **Parameters tuned and reported on the same years.** The walk-forward validation stays
   inside 1998-2010; there is no untouched test period.
4. **Benchmarks that do not match their descriptions.** "Best stock" is described as the
   hindsight best but implemented as yesterday's winner (equation 2), which is why it lost
   99.95%. The sample data figure shows 2020 dates in a 1998-2010 study.

From the code (`Scripts/Strategies/follow_the_loser.py`, `Scripts/utilities.py`):

5. **Their OLMAR never trades.** It updates only when the predicted portfolio return falls
   below epsilon = 0.8, but the prediction is an average of price ratios close to 1.0, so the
   condition is never met and the portfolio stays at equal weights. The paper's OLMAR result
   (12.1584) is identical to CRP's (12.1584) to four decimals.
6. **Their CWMR is not the published CWMR.** The docstring calls it "a simplified version";
   it drops the mean-centering of Li et al.'s update and adds a learning-rate factor. The
   paper's top result belongs to this variant, not to the method it cites.
7. **Dead stocks freeze instead of falling.** Missing prices are forward-filled, so a stock
   that stops trading keeps its last price forever (a price ratio of 1.0). A bankruptcy never
   shows up as a loss.
8. **The day's close may be an after-hours print.** Each day's close is the last row of the
   minute file; the data source includes extended hours. Thin after-hours trades bounce, and
   bounce looks like mean reversion. Not verifiable without their data.

No look-ahead in the wealth calculation: each day's weights use only the previous day's
prices (`b_n[t]` is built from `price_relative_vectors[t-1]`).

## Our replication

Strategies in `strategies/olps/`: `crp.py`, `olmar.py` (Li and Hoi's published OLMAR),
`pamr.py` (PAMR-1 with the paper's tuned epsilon = 0.9, C = 10), `cwmr.py` (the paper's
variant, ported line by line from their code). Universe: 17 equity ETFs (SPY, QQQ, IWM, DIA, EFA,
EEM and the 11 sector ETFs). 2016-01-01 to 2025-01-01, $20,000, fractional shares, idle cash at
the T-bill rate, decisions at 15:30 New York time on data through 15:14, fills at 15:45, SEC fee
on sales. "0 bp" removes slippage only.

Before trusting the results, each algorithm was run on two synthetic prices that alternate
between 1 and 2. OLMAR and PAMR captured almost the full doubling every day, as mean reversion
should; the implementations work.

| Run | Strategy | Costs | CAGR | Sharpe | Max drawdown | Turnover (x equity a year) |
|---|---|---|---|---|---|---|
| 23 | CRP, monthly | 0 bp | 11.9% | 0.62 | -35.3% | 0.4 |
| 22 | CRP, monthly | 1 bp | 11.9% | 0.62 | -35.3% | 0.4 |
| 29 | CWMR (paper variant) | 0 bp | 12.4% | 0.61 | -39.1% | 393 |
| 28 | CWMR (paper variant) | 1 bp | 8.3% | 0.41 | -39.3% | 388 |
| 27 | PAMR (paper settings) | 0 bp | 9.9% | 0.45 | -55.5% | 127 |
| 26 | PAMR (paper settings) | 1 bp | 8.5% | 0.40 | -55.6% | 127 |
| 25 | OLMAR (published) | 0 bp | 7.2% | 0.32 | -51.7% | 298 |
| 24 | OLMAR (published) | 1 bp | 4.0% | 0.21 | -52.9% | 298 |
| 12 | SPY buy and hold | 1 bp | 13.8% | 0.73 | -32.1% | 0 |

Benchmark SPY over the same window: 14.5% a year, -33.8% max drawdown. CWMR's first year is a
warm-up in cash (it replays 252 sessions before trading), which costs it some return.

What this shows:

- **Even free trading does not save them.** With slippage at zero, every mean-reversion
  strategy trailed both SPY and the simple monthly CRP.
- **Costs are the main story.** One basis point per trade, about the spread on a liquid ETF,
  cut OLMAR from 7.2% to 4.0% and CWMR from 12.4% to 8.3%. Individual stocks, which the paper
  used, have wider spreads than these ETFs.
- **The universe differs from the paper's.** Short-term reversal is usually stronger in
  individual stocks than in ETFs, so this test is not a full rebuttal for stocks. Testing on
  the S&P 500 waits for the stock universe (plan step 5). Given the turnover, costs would need
  to stay well under 1 bp per trade for any of these to compete, which individual stocks do
  not offer.

## Applications for btest

Worth adopting:

1. **CRP as a standard baseline.** `olps/crp` is equal weight reset monthly: near-zero turnover,
   11.9% here, and a fairer yardstick than SPY for any strategy that spreads money across
   several ETFs. Use it next to SPY and 60/40 when judging portfolio strategies.
2. **Walk-forward validation.** The paper's rolling train/validate windows are the design
   already planned as G10 (plan step 8); their Figure 5 is a usable spec. Add the piece the
   paper skipped: an untouched holdout, which btest already enforces from 2025-01-01.
3. **Turnover as a first-class number.** btest already reports turnover; this paper shows why
   it belongs next to Sharpe. A rule of thumb from these runs: annual turnover times cost per
   trade is roughly the yearly drag (393 x 1 bp is about 4%, matching CWMR's drop).
4. **The stateless replay pattern.** `olps/cwmr` rebuilds its internal state from the last
   year of prices at every decision, so a strategy with memory can still run live in a fresh
   process. Reuse it for any learning strategy.
5. **The authors' code as a source.** It is MIT-licensed and covers about 30 algorithms. Port
   from it, but check each port against the published papers: two of the five follow-the-loser
   implementations differ from their sources.

Not worth pursuing now:

- **Daily mean-reversion portfolios (PAMR, CWMR, OLMAR, Anticor, RMR)** on ETFs: below SPY
  even without costs, far below with them.
- **Pattern matching and meta-learning ensembles**: the paper's own numbers show 75-99%
  drawdowns for most pattern-matching variants and minutes of compute per backtest, and the
  ensembles are built from the mean-reversion strategies above.

Worth one more test later:

- **FTRL (regularized momentum)**, the paper's best follow-the-winner strategy at a Sharpe of
  1.04 with much lower turnover than the mean-reversion family. It is closer to the momentum
  strategies already in btest and could be added as a lab file with weekly or monthly
  rebalancing.
- **Mean reversion on S&P 500 stocks with realistic spreads**, once step 5 lands, to settle the
  stocks-versus-ETFs question.
