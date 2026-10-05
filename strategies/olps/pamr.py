import numpy as np

from btest.strategy import Strategy


def simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto the probability simplex (Duchi et al. 2008)."""
    u = np.sort(v)[::-1]
    css = np.cumsum(u)
    k = np.arange(1, len(v) + 1)
    rho = k[u - (css - 1) / k > 0][-1]
    return np.maximum(v - (css[rho - 1] - 1) / rho, 0.0)


class PAMR(Strategy):
    """Passive aggressive mean reversion (Li, Hoi and Sahoo, 2012), the PAMR-1 variant. When the
    portfolio's return over the last session beats epsilon, it shifts weight away from that
    session's winners toward its losers, by an amount capped at C. Rebalances every session."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    rebalance = "daily"
    # The NYU paper's tuned settings (its Exhibit A), which beat Li et al.'s epsilon=0.5 here.
    params = {"epsilon": 0.9, "C": 10.0}

    def validate(self):
        if self.params["epsilon"] < 0 or self.params["C"] <= 0:
            raise ValueError("epsilon must be >= 0 and C > 0")

    def decide(self, as_of, data):
        closes = {s: data.history(s, "close", 2) for s in self.universe}
        live = [s for s, c in closes.items() if len(c) == 2]
        if len(live) < 2:
            return None
        x = np.array([closes[s][1] / closes[s][0] for s in live])
        held = data.weights()
        b = np.array([held.get(s, 0.0) for s in live])
        if b.sum() <= 0:
            b = np.full(len(live), 1.0 / len(live))
        else:
            b = b / x
            b = b / b.sum()
        loss = max(0.0, float(b @ x) - self.params["epsilon"])
        dev = x - x.mean()
        denom = float(dev @ dev)
        tau = 0.0 if denom == 0 else min(self.params["C"], loss / denom)
        new = simplex(b - tau * dev)
        return {s: float(v) for s, v in zip(live, new) if v > 1e-6}
