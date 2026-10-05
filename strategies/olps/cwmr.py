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

    The mean and covariance depend on every update since the start, so a decision replays the
    whole common price history of the universe from an equal-weight start, as the authors' code
    does. A live decision (a fresh process) replays it all; a backtest keeps the state between
    sessions and applies one update a day, which gives the same numbers."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"epsilon": 0.89, "theta": 0.92, "eta": 0.93}

    def _step(self, mu, sigma, x):
        p = self.params
        k = len(mu)
        denom = x @ sigma @ x
        lam = p["eta"] * max(0.0, (mu @ x - p["epsilon"]) / (denom + 1e-15)) if denom > 0 else 0.0
        mu = mu - lam * (sigma @ x)
        inv = np.linalg.inv(sigma + np.eye(k) * 1e-12) + 2 * lam * p["theta"] * np.outer(x, x)
        return simplex(mu), np.linalg.inv(inv)

    def decide(self, as_of, data):
        closes = {s: data.history(s, "close") for s in self.universe}
        live = tuple(s for s, c in closes.items() if len(c) >= 2)
        if len(live) < 2:
            return None
        n = min(len(closes[s]) for s in live)
        rel = np.column_stack([closes[s][-n:][1:] / closes[s][-n:][:-1] for s in live])
        # The last row uses today's price at the cutoff; tomorrow it is replaced by today's
        # close. So the cached state covers completed sessions only, and today's row is
        # applied to a copy.
        done = rel[:-1]
        state = getattr(self, "_state", None)
        if state and state["live"] == live and state["rows"] == len(done) - 1:
            mu, sigma = self._step(state["mu"], state["sigma"], done[-1])
        elif state and state["live"] == live and state["rows"] == len(done):
            mu, sigma = state["mu"], state["sigma"]
        else:
            mu, sigma = np.full(len(live), 1.0 / len(live)), np.eye(len(live))
            for x in done:
                mu, sigma = self._step(mu, sigma, x)
        self._state = {"live": live, "rows": len(done), "mu": mu, "sigma": sigma}
        mu, _ = self._step(mu, sigma, rel[-1])
        return {s: float(w) for s, w in zip(live, mu) if w > 1e-6}
