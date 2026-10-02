import numpy as np

from btest.strategy import Strategy


def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


class TrendFilter(Strategy):
    """Holds the symbol while its daily close is above its moving average, cash otherwise.
    Decides at each day's close and trades at the next day's open. buffer is a band around
    the average (0.01 = 1%) that cuts whipsaw trades near the line."""

    timeframe = "1D"
    params = {"symbol": "SPY", "length": 200, "buffer": 0.0, "allocation": 1.0}

    def validate(self):
        if self.params["length"] < 2 or self.params["buffer"] < 0:
            raise ValueError("need length >= 2 and buffer >= 0")

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        closes = ctx.history(bar.symbol, "close", p["length"])
        if len(closes) < p["length"]:
            return
        ma = closes.mean()
        holding = ctx.position(bar.symbol) > 0
        if bar.close > ma * (1 + p["buffer"]) and not holding:
            ctx.order_target_percent(bar.symbol, p["allocation"])
        elif bar.close < ma * (1 - p["buffer"]) and holding:
            ctx.order_target(bar.symbol, 0)

    def signals(self, a):
        p = self.params
        ma = rolling_mean(a["close"], p["length"])
        w = np.full(len(ma), np.nan)
        w[a["close"] > ma * (1 + p["buffer"])] = p["allocation"]
        w[a["close"] < ma * (1 - p["buffer"])] = 0.0
        return w
