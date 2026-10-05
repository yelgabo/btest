import numpy as np

from btest.strategy import Strategy


def simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto the probability simplex (Duchi et al. 2008)."""
    u = np.sort(v)[::-1]
    css = np.cumsum(u)
    k = np.arange(1, len(v) + 1)
    rho = k[u - (css - 1) / k > 0][-1]
    return np.maximum(v - (css[rho - 1] - 1) / rho, 0.0)


class CWMRVariant(Strategy):
    """The confidence-weighted mean reversion variant from Lahanis, Liu and Zhou's NYU paper,
    ported from their MIT-licensed code (Scripts/Strategies/follow_the_loser.py, cwmr). It is a
    simplified form of Li et al.'s CWMR: it keeps a mean portfolio and a covariance matrix and
    shifts weight away from the last session's winners. The paper reports it as the best
    strategy (1,590x, 1998-2010, no costs).

    The mean and covariance depend on every past update, so each decision replays the last
    replay_days sessions from an equal-weight start. That keeps it stateless, which the live
    system needs (a fresh process per decision)."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    rebalance = "daily"
    params = {"epsilon": 0.89, "theta": 0.92, "eta": 0.93, "replay_days": 252}

    def validate(self):
        if self.params["replay_days"] < 20:
            raise ValueError("replay_days must be at least 20")

    def decide(self, as_of, data):
        p = self.params
        n = p["replay_days"] + 1
        closes = {s: data.history(s, "close", n) for s in self.universe}
        live = [s for s, c in closes.items() if len(c) == n]
        if len(live) < 2:
            return None
        rel = np.column_stack([closes[s][1:] / closes[s][:-1] for s in live])
        k = len(live)
        mu = np.full(k, 1.0 / k)
        sigma = np.eye(k)
        for x in rel:
            denom = x @ sigma @ x
            lam = p["eta"] * max(0.0, (mu @ x - p["epsilon"]) / (denom + 1e-15)) if denom > 0 \
                else 0.0
            mu = mu - lam * (sigma @ x)
            inv = np.linalg.inv(sigma + np.eye(k) * 1e-12) + 2 * lam * p["theta"] * np.outer(x, x)
            sigma = np.linalg.inv(inv)
            mu = simplex(mu)
        return {s: float(w) for s, w in zip(live, mu) if w > 1e-6}
