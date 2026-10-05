import numpy as np

from btest.strategy import Strategy


def simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto the probability simplex (Duchi et al. 2008)."""
    u = np.sort(v)[::-1]
    css = np.cumsum(u)
    k = np.arange(1, len(v) + 1)
    rho = k[u - (css - 1) / k > 0][-1]
    return np.maximum(v - (css[rho - 1] - 1) / rho, 0.0)


class OLMAR(Strategy):
    """On-line moving average reversion (Li and Hoi, ICML 2012). Predicts each price will return
    to its moving average, then moves the portfolio the smallest distance that makes the
    predicted portfolio return at least epsilon. Rebalances every session. The weights held
    going in are read back from the account, so nothing is remembered between decisions."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    rebalance = "daily"
    params = {"window": 5, "epsilon": 10.0}

    def validate(self):
        if self.params["window"] < 2 or self.params["epsilon"] <= 1:
            raise ValueError("window must be >= 2 and epsilon > 1")

    def decide(self, as_of, data):
        w = self.params["window"]
        closes = {s: data.history(s, "close", w + 1) for s in self.universe}
        live = [s for s, c in closes.items() if len(c) == w + 1]
        if len(live) < 2:
            return None
        price = np.array([closes[s][-1] for s in live])
        predicted = np.array([closes[s][-w:].mean() for s in live]) / price
        moved = np.array([closes[s][-1] / closes[s][-2] for s in live])
        held = data.weights()
        b = np.array([held.get(s, 0.0) for s in live])
        if b.sum() <= 0:
            b = np.full(len(live), 1.0 / len(live))
        else:
            # Undo today's drift to recover the portfolio chosen yesterday, as the paper does.
            b = b / moved
            b = b / b.sum()
        dev = predicted - predicted.mean()
        denom = float(dev @ dev)
        step = 0.0 if denom == 0 else max(0.0, (self.params["epsilon"] - b @ predicted) / denom)
        new = simplex(b + step * dev)
        return {s: float(x) for s, x in zip(live, new) if x > 1e-6}
