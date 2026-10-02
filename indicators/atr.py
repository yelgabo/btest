import numpy as np

from btest.indicator import Indicator


class ATR(Indicator):
    """Average true range with Wilder's smoothing: the typical size of a candle including gaps,
    in price units."""

    params = {"length": 14}
    pane = "own"

    def compute(self, c):
        n = self.params["length"]
        high, low, close = c["high"], c["low"], c["close"]
        prev = np.concatenate(([close[0]], close[:-1]))
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
        atr = np.full(len(tr), np.nan)
        if len(tr) >= n:
            atr[n - 1] = tr[:n].mean()
            for i in range(n, len(tr)):
                atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
        return {"atr": atr}
