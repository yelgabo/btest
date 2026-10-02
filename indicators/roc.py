import numpy as np

from btest.indicator import Indicator


class RateOfChange(Indicator):
    """Percent change over the last length candles; 252 on a daily chart is the 12-month return
    that trend/momentum_12m trades on."""

    params = {"length": 252}
    pane = "own"
    levels = [0]

    def compute(self, c):
        n = self.params["length"]
        close = c["close"]
        roc = np.full(len(close), np.nan)
        roc[n:] = (close[n:] / close[:-n] - 1) * 100
        return {"roc %": roc}
