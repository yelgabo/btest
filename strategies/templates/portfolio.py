"""Portfolio strategy template: every setting and every data call a decide() strategy can use.

It runs as is and places no trades. Duplicate it, then fill in decide(). Portfolio strategies
make one decision per scheduled session, the same way the live system trades them: at 15:30
New York time (12:30 on half days) on data through the 15:14 bar, with orders filling at 15:45.
"""

import numpy as np

from btest.portfolio import Targets  # only needed for options
from btest.strategy import Strategy


class MyPortfolio(Strategy):
    """One line on the idea, then the rules in plain words."""

    # Symbols the strategy may hold or read. Plain literal list; the Run panel shows it and
    # the run loads exactly these.
    universe = ["SPY", "AGG"]

    # Which sessions decide() is called on: "daily", "weekly" (last session of the week),
    # "month_end" or "month_start".
    rebalance = "month_end"

    # Tunable inputs, available as self.params["name"] and editable in the Run panel.
    params = {"lookback": 126, "stock_weight": 0.6}

    def validate(self):
        if self.params["lookback"] < 2:
            raise ValueError("lookback must be at least 2")

    # -------------------------------------------------------------------------------------
    # decide(as_of, data) returns one of:
    #   {"SPY": 0.6, "AGG": 0.4}   target weights of equity for the whole portfolio; symbols
    #                              left out are sold; weights may add up to less than 1 (the
    #                              rest stays in cash). No leverage: buys are capped at cash.
    #   Targets(weights={...}, options={"XLF240315P00038000": -2})
    #                              the same plus option contracts (negative = written).
    #   None                       keep everything as it is (no orders).
    #
    # as_of                        the decision time, a timezone-aware UTC datetime
    # data.today                   the New York session date
    # data.symbols                 the universe
    # data.history(sym, field="close", n=None)
    #                              numpy array of daily values, adjusted for splits and
    #                              dividends; field is open, high, low, close or volume. The
    #                              last value is today as of the cutoff (today's "close" is the
    #                              15:14 price). Empty before the symbol's data starts.
    # data.frame(field="close", n=None)
    #                              the same for all symbols as a polars DataFrame: a date
    #                              column plus one column per symbol, null before data starts
    # data.price(sym)              last traded price at the cutoff, unadjusted
    # data.position(sym), data.positions()
    #                              shares held (fractional unless the run turns that off)
    # data.weights()               current weights of equity at cutoff prices
    # data.cash, data.equity       dollars at the cutoff
    # data.rate()                  3-month T-bill yield known yesterday (0.05 = 5%)
    # data.month_position()        (sessions since the month started, sessions until it ends),
    #                              both counting today as 1
    # data.report(key, value)      a note saved with the run
    # Options (contracts and 30-minute bars ingested with `btest ingest-options`):
    # data.expiries(underlying)    upcoming expiry dates with data
    # data.option_chain(underlying, expiry, right="P")
    #                              polars DataFrame: symbol, strike, price (last trade before
    #                              the cutoff), volume (contracts traded today by the cutoff)
    # data.option_positions()      {option symbol: contracts}
    #
    # The engine: notional orders sized at cutoff prices, sells before buys, slippage and the
    # SEC fee on sales, idle cash earning T-bills (if ticked), dividends paid in cash on the
    # ex-date, written puts must be fully secured by cash and are assigned at expiry when in
    # the money. Keep state only in what data shows you (positions, prices): the live system
    # starts a fresh process for every decision, so attributes set on self do not survive.
    # -------------------------------------------------------------------------------------
    def decide(self, as_of, data):
        p = self.params
        close = data.history("SPY", "close", p["lookback"] + 1)
        if len(close) <= p["lookback"]:
            return None  # not enough history yet
        momentum = close[-1] / close[0] - 1
        _ = (np, Targets, momentum)  # remove once you use them
        # --- your rule: return weights, e.g. -----------------------------------------------
        # return {"SPY": p["stock_weight"], "AGG": 1 - p["stock_weight"]}
        return None
