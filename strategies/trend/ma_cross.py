import numpy as np

from btest.strategy import Strategy


def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Mean of the last n values at each index, NaN until n values exist."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


class MovingAverageCross(Strategy):
    """Long when the fast moving average of adjusted close is above the slow one, flat
    otherwise. Windows are in minute bars (390 per regular session)."""

    params = {"fast": 30, "slow": 390, "symbol": "SPY", "allocation": 1.0}

    def validate(self):
        if not 0 < self.params["fast"] < self.params["slow"]:
            raise ValueError("need 0 < fast < slow")

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        closes = ctx.history(bar.symbol, "close", p["slow"])
        if len(closes) < p["slow"]:
            return
        fast = closes[-p["fast"]:].mean()
        slow = closes.mean()
        holding = ctx.position(bar.symbol) > 0
        if fast > slow and not holding:
            ctx.order_target_percent(bar.symbol, p["allocation"])
        elif fast < slow and holding:
            ctx.order_target(bar.symbol, 0)

    def signals(self, a):
        p = self.params
        fast = rolling_mean(a["close"], p["fast"])
        slow = rolling_mean(a["close"], p["slow"])
        w = np.full(len(fast), np.nan)
        w[fast > slow] = p["allocation"]
        w[fast < slow] = 0.0
        return w
