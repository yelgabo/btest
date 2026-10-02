"""Strategy template: every hook and every call a strategy can use.

It runs as is and places no trades. Fill in on_bar (and signals, if you want sweeps).
Delete the comments you no longer need.
"""

import numpy as np

# Strategy is the only required base class. numpy, polars, pandas and the Python standard
# library are available to import.
from btest.strategy import Strategy


class MyStrategy(Strategy):
    """One line on the idea, then the rules in plain words."""

    # -------------------------------------------------------------------------------------
    # Settings, read before anything runs. Both must be plain literals: the editor reads them
    # without running your code to build the Run panel.
    # -------------------------------------------------------------------------------------

    # Bar size the strategy trades on: "1m", "5m", "15m", "30m", "1h" or "1D". Lengths in
    # params count bars of this size; decisions happen at each bar's close.
    timeframe = "1D"

    # Tunable inputs. Every key appears in the Run panel, can be swept, and is available as
    # self.params["name"]. Unknown keys passed to a run are rejected.
    params = {
        "symbol": "SPY",      # which symbol to trade (the Run panel picks what data is loaded)
        "length": 20,         # example: a lookback in bars
        "allocation": 1.0,    # example: share of equity to put in, 0 to 1
    }

    # -------------------------------------------------------------------------------------
    # Optional: reject parameter combinations that make no sense. Raise ValueError; sweeps
    # skip those combinations and single runs show the message.
    # -------------------------------------------------------------------------------------
    def validate(self):
        if self.params["length"] < 1:
            raise ValueError("length must be at least 1")

    # -------------------------------------------------------------------------------------
    # Optional: called once before the first bar. Set up any state you keep between bars
    # here (counters, last signal, ...); don't keep state in class attributes.
    # -------------------------------------------------------------------------------------
    def on_start(self, ctx):
        pass  # e.g. self.last_signal = 0.0

    # -------------------------------------------------------------------------------------
    # Required: called once per bar per symbol, in time order, after the bar has closed.
    # This is where the strategy decides.
    #
    # bar (the bar that just closed):
    #   bar.symbol          "SPY"
    #   bar.ts              bar start time, a timezone-aware UTC datetime
    #   bar.date            New York trading date (datetime.date)
    #   bar.open/high/low/close/volume
    #                       split- and dividend-adjusted, like the charts
    #   bar.raw_open, bar.raw_close
    #                       prices as traded that day (fills and cash use these)
    #
    # ctx (the account and the market so far):
    #   ctx.now             time of the current bar (UTC)
    #   ctx.cash            cash in dollars
    #   ctx.equity          cash + positions at the latest close
    #   ctx.position(sym)   shares held (negative when short); splits rescale it for you
    #   ctx.history(sym, field="close", n=None)
    #                       numpy array of the last n values up to and including this bar;
    #                       field is "open", "high", "low", "close" or "volume" (adjusted).
    #                       Shorter than n until enough bars exist. n=None gives everything.
    #
    # Orders (all are market orders filled at the NEXT bar's open, never this bar's close):
    #   ctx.order(sym, qty)                  buy qty shares (negative qty sells)
    #   ctx.order_target(sym, shares)        trade whatever gets you to that many shares
    #   ctx.order_target_percent(sym, pct)   trade to pct of equity (0 = flat, 1 = all in,
    #                                        negative = short, if allowed)
    #
    # What the engine does with orders:
    #   - Buys are capped at available cash; there is no margin.
    #   - Selling below zero is clipped to flat unless "Allow short selling" is ticked.
    #   - Costs: slippage (bps of price), commission per share, SEC fee on sells.
    #   - Dividends are paid in cash on the ex-date; splits adjust shares automatically.
    #   - Several orders on the same bar for the same symbol are combined into one fill.
    # -------------------------------------------------------------------------------------
    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return  # with several symbols loaded, on_bar is called for each of them

        closes = ctx.history(bar.symbol, "close", p["length"])
        if len(closes) < p["length"]:
            return  # not enough history yet

        holding = ctx.position(bar.symbol) > 0

        # --- your entry rule: decide when to buy -------------------------------------------
        should_buy = False
        if should_buy and not holding:
            ctx.order_target_percent(bar.symbol, p["allocation"])

        # --- your exit rule: decide when to sell -------------------------------------------
        should_sell = False
        if should_sell and holding:
            ctx.order_target(bar.symbol, 0)

    # -------------------------------------------------------------------------------------
    # Optional: called once after the last bar. Positions still open are valued at the last
    # close; they are not sold for you.
    # -------------------------------------------------------------------------------------
    def on_end(self, ctx):
        pass

    # -------------------------------------------------------------------------------------
    # Optional fast path, needed for sweeps (about 300x faster than on_bar on minute bars).
    # Compute the whole history at once and return one target weight per bar:
    #
    #   a["open"], a["high"], a["low"], a["close"], a["volume"]   adjusted, numpy float arrays
    #   a["raw_open"], a["raw_close"]                             as traded
    #   a["ts"]     bar start times, numpy datetime64[us] in UTC
    #   a["date"]   New York trading dates, numpy datetime64[D]
    #
    # Return a float array the same length: the weight to switch to at that bar's close, like
    # order_target_percent (0 = flat, 1 = all in, negative = short if allowed), or NaN for
    # "no change". Use only data up to each bar. The fast path trades one symbol: the one
    # picked in the Sweep panel.
    #
    # It must make the same decisions as on_bar. Check with:
    #   uv run btest parity strategies/<file>.py SPY --start 2016-01-01 --end 2025-01-01
    # Delete this method if you don't need sweeps.
    # -------------------------------------------------------------------------------------
    def signals(self, a):
        weights = np.full(len(a["close"]), np.nan)
        # --- same entry and exit rules as on_bar, as arrays ---------------------------------
        # e.g. weights[entry_mask] = self.params["allocation"]; weights[exit_mask] = 0.0
        return weights
