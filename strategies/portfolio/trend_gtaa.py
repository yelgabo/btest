import numpy as np

from btest.strategy import Strategy


class TrendGTAA(Strategy):
    """Faber's tactical asset allocation: each asset class gets an equal slice and is held only
    while its price is above its moving average (10 months by default), checked at each month
    end. Slices that are out sit in cash earning the T-bill rate. size_by_vol gives calmer
    assets bigger slices (inverse volatility) instead of equal ones."""

    universe = ["SPY", "EFA", "IEF", "VNQ", "DBC"]
    rebalance = "month_end"
    params = {"sma_days": 210, "size_by_vol": False, "vol_days": 63}

    def validate(self):
        if self.params["sma_days"] < 2 or self.params["vol_days"] < 2:
            raise ValueError("sma_days and vol_days must be at least 2")

    def decide(self, as_of, data):
        p = self.params
        slices = {}
        for s in self.universe:
            close = data.history(s, "close", p["sma_days"])
            if len(close) < p["sma_days"]:
                continue
            if p["size_by_vol"]:
                r = np.diff(np.log(close[-p["vol_days"] - 1:]))
                slices[s] = 1.0 / max(r.std(), 1e-6)
            else:
                slices[s] = 1.0
            if close[-1] <= close.mean():
                slices[s] = -slices[s]
        total = sum(abs(v) for v in slices.values())
        if not total:
            return None
        return {s: v / total for s, v in slices.items() if v > 0}
