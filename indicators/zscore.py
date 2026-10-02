import numpy as np

from btest.indicator import Indicator


class ZScore(Indicator):
    """Standard deviations between the close and its rolling mean, the signal that
    mean_reversion/zscore trades on. Set length to the strategy's window in candles."""

    params = {"length": 390}
    pane = "own"
    levels = [-2, 0, 2]

    def compute(self, c):
        n = self.params["length"]
        x = c["close"]
        z = np.full(len(x), np.nan)
        if len(x) >= n:
            d = x - x[0]
            c1 = np.cumsum(np.insert(d, 0, 0.0))
            c2 = np.cumsum(np.insert(d * d, 0, 0.0))
            mean = (c1[n:] - c1[:-n]) / n
            std = np.sqrt(np.maximum((c2[n:] - c2[:-n]) / n - mean * mean, 0.0))
            with np.errstate(divide="ignore", invalid="ignore"):
                z[n - 1:] = np.where(std > 0, (d[n - 1:] - mean) / std, np.nan)
        return {"z": z}
