import numpy as np

from btest.indicator import Indicator


class RealizedVolatility(Indicator):
    """Annualized standard deviation of log returns over the last length candles, in percent.
    per_year is candles per year: 252 on daily charts, 252 * 26 on 15m."""

    params = {"length": 20, "per_year": 252}
    pane = "own"
    levels = [15]

    def compute(self, c):
        n = self.params["length"]
        r = np.diff(np.log(c["close"]))
        vol = np.full(len(c["close"]), np.nan)
        for i in range(n, len(c["close"])):
            vol[i] = r[i - n:i].std() * np.sqrt(self.params["per_year"]) * 100
        return {"vol %": vol}
