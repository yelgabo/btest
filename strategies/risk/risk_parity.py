import numpy as np

from btest.strategy import Strategy


class RiskParity(Strategy):
    """Weights stocks, long bonds and gold by inverse volatility, then scales the whole mix so
    its estimated volatility is target_vol, never above 100% invested (a cash account has no
    leverage). Rebalanced at each month end."""

    universe = ["SPY", "TLT", "GLD", "IEF"]
    rebalance = "month_end"
    params = {"vol_days": 63, "target_vol": 0.10}

    def validate(self):
        if self.params["vol_days"] < 10 or not 0 < self.params["target_vol"] <= 1:
            raise ValueError("vol_days must be >= 10 and target_vol in (0, 1]")

    def decide(self, as_of, data):
        p = self.params
        n = p["vol_days"] + 1
        closes = {s: data.history(s, "close", n) for s in self.universe}
        ready = [s for s, c in closes.items() if len(c) == n]
        if not ready:
            return None
        rets = np.column_stack([np.diff(np.log(closes[s])) for s in ready])
        vols = rets.std(axis=0) * np.sqrt(252)
        w = (1 / vols) / (1 / vols).sum()
        port_vol = float(np.sqrt(w @ (np.cov(rets, rowvar=False) * 252) @ w))
        scale = min(1.0, p["target_vol"] / port_vol) if port_vol > 0 else 1.0
        return {s: float(x * scale) for s, x in zip(ready, w)}
