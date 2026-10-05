from datetime import date, datetime


class Bar:
    __slots__ = ("symbol", "ts", "date", "open", "high", "low", "close", "volume",
                 "raw_open", "raw_close")

    def __init__(self, symbol, ts, date, open, high, low, close, volume, raw_open, raw_close):
        self.symbol: str = symbol
        self.ts: datetime = ts
        self.date: date = date
        self.open: float = open
        self.high: float = high
        self.low: float = low
        self.close: float = close
        self.volume: float = volume
        self.raw_open: float = raw_open
        self.raw_close: float = raw_close


class Strategy:
    """Subclass and override on_bar. Prices on bars and in ctx.history are split- and
    dividend-adjusted; fills and cash use raw prices."""

    params: dict = {}
    # Bar size the strategy trades on: 1m, 5m, 15m, 30m, 1h or 1D. Windows in params count bars
    # of this size, and orders fill at the next bar's open.
    timeframe: str = "1m"
    # Portfolio strategies (those with decide): the symbols they may hold, and which sessions
    # they decide on: "daily", "weekly", "month_end" or "month_start".
    universe: list = []
    rebalance: str = "daily"

    def __init__(self, **params):
        unknown = set(params) - set(type(self).params)
        if unknown:
            raise ValueError(f"unknown params for {type(self).__name__}: {sorted(unknown)}")
        self.params = {**type(self).params, **params}
        self.validate()

    def validate(self) -> None:
        """Raise ValueError for parameter combinations that make no sense. Sweeps skip them."""

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar: Bar) -> None:
        pass

    def on_end(self, ctx) -> None:
        pass

    def signals(self, a: dict):
        """Optional fast path for one symbol. `a` maps field names (adjusted open, high, low,
        close, volume, raw_open, raw_close, ts, date) to arrays. Return a float array of target
        portfolio weights, one per bar, using only data up to that bar; NaN means no change.
        A change in weight at bar i orders that weight at bar i's close, filled at bar i+1's
        open, exactly like ctx.order_target_percent."""
        raise NotImplementedError(f"{type(self).__name__} has no signals() fast path")

    def decide(self, as_of, data):
        """Portfolio path. Called once per scheduled session at 15:30 New York time (earlier on
        half days) with data through the 15:14 bar, the same view the live system has. Return
        {symbol: weight} for the whole portfolio, a btest.portfolio.Targets (adds option
        contracts), or None to leave positions as they are. Orders fill at 15:45."""
        raise NotImplementedError(f"{type(self).__name__} has no decide()")


def has_decide(cls: type) -> bool:
    return cls.decide is not Strategy.decide

