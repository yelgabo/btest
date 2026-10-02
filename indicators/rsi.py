import numpy as np

from btest.indicator import Indicator


class RSI(Indicator):
    """Relative strength index with Wilder's smoothing, 0 to 100."""

    params = {"length": 14}
    pane = "own"
    levels = [30, 70]

    def compute(self, c):
        n = self.params["length"]
        close = c["close"]
        delta = np.diff(close, prepend=close[0])
        gain, loss = np.clip(delta, 0, None), np.clip(-delta, 0, None)
        rsi = np.full(len(close), np.nan)
        if len(close) <= n:
            return {"rsi": rsi}
        avg_gain, avg_loss = gain[1:n + 1].mean(), loss[1:n + 1].mean()
        for i in range(n, len(close)):
            if i > n:
                avg_gain = (avg_gain * (n - 1) + gain[i]) / n
                avg_loss = (avg_loss * (n - 1) + loss[i]) / n
            rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        return {"rsi": rsi}
