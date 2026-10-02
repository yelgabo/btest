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

    def __init__(self, **params):
        unknown = set(params) - set(type(self).params)
        if unknown:
            raise ValueError(f"unknown params for {type(self).__name__}: {sorted(unknown)}")
        self.params = {**type(self).params, **params}

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar: Bar) -> None:
        pass

    def on_end(self, ctx) -> None:
        pass
