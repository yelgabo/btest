import numpy as np

from btest.strategy import Strategy


class TimeSeriesMomentum(Strategy):
    """Holds the symbol while its return over the last lookback days beats threshold (an
    annual hurdle such as a T-bill yield, 0.04 = 4%), cash otherwise. Checks every
    rebalance_days days."""

    timeframe = "1D"
    params = {"symbol": "SPY", "lookback": 252, "rebalance_days": 21, "threshold": 0.0,
              "allocation": 1.0}

    def validate(self):
        if self.params["lookback"] < 1 or self.params["rebalance_days"] < 1:
            raise ValueError("lookback and rebalance_days must be >= 1")

    def _hurdle(self):
        p = self.params
        return (1 + p["threshold"]) ** (p["lookback"] / 252) - 1

    def on_start(self, ctx):
        self.last = 0.0

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        closes = ctx.history(bar.symbol, "close")
        i = len(closes) - 1
        if i < p["lookback"] or (i - p["lookback"]) % p["rebalance_days"]:
            return
        momentum = closes[-1] / closes[-1 - p["lookback"]] - 1
        want = p["allocation"] if momentum > self._hurdle() else 0.0
        # Only act on a change of mind; re-sizing an unchanged position each month would just
        # trade the drift.
        if want != self.last:
            ctx.order_target_percent(bar.symbol, want)
            self.last = want

    def signals(self, a):
        p = self.params
        c = a["close"]
        w = np.full(len(c), np.nan)
        for i in range(p["lookback"], len(c), p["rebalance_days"]):
            momentum = c[i] / c[i - p["lookback"]] - 1
            w[i] = p["allocation"] if momentum > self._hurdle() else 0.0
        return w
