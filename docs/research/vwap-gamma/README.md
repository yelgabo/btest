# VWAP band fade on SPY, 2016-2024

A post on X (@t38p_flow, 2026-10-12) showed a bot fading SPXW at large dealer-gamma strikes
near the edge of VWAP bands: three short scalps, all winners. Testing the full idea needs
historical open interest by strike to compute gamma exposure, which btest does not have. This is
step one: the VWAP band fade alone, with no gamma filter. If the plain fade has no edge, a gamma
filter would have to create one by itself.

## Rule

`strategies/intraday/vwap_band_fade.py`, 1-minute SPY bars. The session VWAP starts at 9:30 and
the bands are the volume-weighted standard deviation of the typical price around it. A bar
closing 2 bands above VWAP opens a short; 2 bands below opens a long. The trade closes at VWAP,
at 3 bands against, or at 15:50. Entries from 10:00 to 15:30. Orders fill at the next bar's open.
These are the defaults, set before any run and not tuned.

## Results

Website runs 102-105. $100,000, shorting allowed, SEC fee on sales, no commission.

| Run | Sides | Slippage | CAGR | Sharpe | Max DD | Trades |
|---|---|---|---|---|---|---|
| 102 | both | 0 bp | -6.0% | -0.98 | -43.9% | 4,611 |
| 103 | both | 1 bp | -15.2% | -2.29 | -77.6% | 4,611 |
| 104 | long | 1 bp | -8.0% | -1.67 | -54.0% | 2,408 |
| 105 | short | 1 bp | -7.9% | -1.85 | -52.6% | 2,210 |

SPY buy and hold over the same window: 14.5% CAGR, Sharpe 0.73.

The fade loses before costs. `fade_trades.py` (output in `outputs/fade_trades.out`) lists every
trade gross of costs: 4,611 trades, a 58.9% win rate, a median of +6.3 bp and a mean of
-0.93 bp. Trades that reach VWAP average +15.8 bp. Trades still open at 15:50 average -32.5 bp,
and stops average -17.3 bp. These are trend days where price leaves the band and never comes
back. Both sides lose by about the same amount, and only 2016, 2017 and 2019 are positive.

At about two trades a day, 1 bp of slippage per side costs roughly 2 bp per trade, twice the
size of the gross loss.

## What would change the answer

- A gamma filter. The post's claim is that large positive-gamma strikes pin price, so fades
  there should avoid the trend days that sink this version. Testing it needs daily open interest
  by strike (ThetaData, ORATS, Cboe DataShop or Polygon), not just price bars.
- Skipping trend days by some other rule, such as the opening range or the prior day's range.
  Any such filter chosen by looking at these results is fitted to them and needs the 2025+
  holdout once, untouched by tuning.
