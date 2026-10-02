import numpy as np

from btest.strategy import Strategy


def rolling_zscore(x: np.ndarray, n: int) -> np.ndarray:
    """How many standard deviations each value sits from the mean of the last n values
    (itself included). NaN until n values exist or when the window is flat."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    # Centre on the first price so the running sums stay small and the variance keeps its
    # precision; raw squared prices near 400 would cancel most of it away.
    d = x - x[0]
    c1 = np.cumsum(np.insert(d, 0, 0.0))
    c2 = np.cumsum(np.insert(d * d, 0, 0.0))
    mean = (c1[n:] - c1[:-n]) / n
    var = np.maximum((c2[n:] - c2[:-n]) / n - mean * mean, 0.0)
    std = np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (d[n - 1:] - mean) / std
    z[std == 0] = np.nan
    out[n - 1:] = z
    return out


class ZScoreReversion(Strategy):
    """Long-only mean reversion. Buys when the close is more than entry_z standard deviations
    below its rolling mean (window in minute bars, 390 = one session) and sells once it is
    back above exit_z. Holds overnight."""

    params = {"symbol": "SPY", "window": 390, "entry_z": 2.0, "exit_z": 0.0, "allocation": 1.0}

    def validate(self):
        p = self.params
        if p["window"] < 2:
            raise ValueError("window must be at least 2")
        if p["exit_z"] <= -p["entry_z"]:
            raise ValueError("exit_z must be above -entry_z, or every entry exits at once")

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        closes = ctx.history(bar.symbol, "close", p["window"])
        if len(closes) < p["window"]:
            return
        z = rolling_zscore(closes, p["window"])[-1]
        if np.isnan(z):
            return
        holding = ctx.position(bar.symbol) > 0
        if z < -p["entry_z"] and not holding:
            ctx.order_target_percent(bar.symbol, p["allocation"])
        elif z > p["exit_z"] and holding:
            ctx.order_target(bar.symbol, 0)

    def signals(self, a):
        p = self.params
        z = rolling_zscore(a["close"], p["window"])
        w = np.full(len(z), np.nan)
        w[z < -p["entry_z"]] = p["allocation"]
        w[z > p["exit_z"]] = 0.0
        return w
