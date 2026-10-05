"""Online portfolio selection algorithms for btest strategies.

Ports of the algorithms in Lahanis, Liu and Zhou, "Online Quantitative Trading Strategies" (NYU
Stern, 2025), from the authors' MIT-licensed code (github.com/nglahani/Online-Quantitative-
Trading-Strategies, commit 7c2e88d). Each algorithm is a class that observes one row of price
ratios at a time (`update`) and reports the portfolio to hold next (`portfolio`). Run over a
history of rows, the sequence of portfolios equals the authors' functions; tests/test_olps.py
checks this against their code.

Where the port deliberately differs from the authors' code, the class docstring says so:
- `UniversalPortfolios` and `AggregationSimple` take a seed; the originals draw unseeded random
  portfolios, so their results change from run to run.
- `MetaExperts` (fast universalization, online gradient and online Newton updates) keeps each
  base expert running from day to day. The originals restart every expert from scratch over the
  whole history at each step, which costs O(T^2) and is not how these methods are described.

`OnlineStrategy` turns any of them into a btest portfolio strategy: at each decision it replays
the universe's common price history (completed sessions at closing prices, then today at the
cutoff price), so a live decision in a fresh process gets the same portfolio as a backtest,
which keeps the state between sessions and applies one update a day.
"""

import copy

import numpy as np
from scipy.optimize import minimize

from btest.strategy import Strategy

EPS = 1e-15


def project_to_simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto the probability simplex (the authors' helper)."""
    n = len(v)
    u = np.sort(v)[::-1]
    cssv = np.cumsum(u) - 1
    rho = np.nonzero(u > cssv / np.arange(1, n + 1))[0][-1]
    theta = cssv[rho] / (rho + 1.0)
    return np.maximum(v - theta, 0)


def l1_median(data: np.ndarray, max_iter: int = 100, tol: float = 1e-5) -> np.ndarray:
    """Weiszfeld iteration for the L1 (geometric) median (the authors' helper)."""
    mu = np.mean(data, axis=0)
    for _ in range(max_iter):
        distances = np.linalg.norm(data - mu, axis=1)
        distances[distances < 1e-10] = 1e-10
        weights = 1.0 / distances[:, np.newaxis]
        mu_new = np.sum(weights * data, axis=0) / np.sum(weights, axis=0)
        if np.linalg.norm(mu_new - mu) < tol:
            break
        mu = mu_new
    return mu


class Online:
    """Observe price-ratio rows one at a time; `portfolio()` is what to hold next."""

    def __init__(self, n: int):
        self.n = n
        self.b = np.full(n, 1.0 / n)

    def update(self, x: np.ndarray) -> None:
        raise NotImplementedError

    def portfolio(self) -> np.ndarray:
        return self.b


# ---------------------------------------------------------------- follow the winner


class UniversalPortfolios(Online):
    """Cover's universal portfolio, approximated by num_portfolios random portfolios weighted
    by wealth ** tau."""

    def __init__(self, n, num_portfolios=3, tau=0.3, seed=0):
        super().__init__(n)
        self.portfolios = np.random.RandomState(seed).dirichlet(np.ones(n), size=num_portfolios)
        self.wealth = np.ones(num_portfolios)
        self.tau = tau

    def portfolio(self):
        w = np.average(self.portfolios, axis=0, weights=self.wealth ** self.tau)
        return w / w.sum()

    def update(self, x):
        self.wealth = self.wealth * self.portfolios.dot(x)


class ExponentialGradient(Online):
    """Helmbold et al.'s exponential gradient, blended with the previous portfolio by
    `smoothing`. The paper used smoothing = 0.0, which never moves the portfolio (it is then
    CRP); smoothing = 1.0 is the published algorithm."""

    def __init__(self, n, learning_rate=0.05, smoothing=1.0):
        super().__init__(n)
        self.lr, self.smoothing = learning_rate, smoothing

    def update(self, x):
        ret = np.dot(self.b, x)
        factor = self.lr * (x / (ret + EPS) - 1) + 1
        computed = self.b * factor
        computed /= np.sum(computed)
        new = (1 - self.smoothing) * self.b + self.smoothing * computed
        self.b = new / np.sum(new)


class FollowTheLeader(Online):
    """Weights proportional to each asset's cumulative growth ** alpha, blended with the
    previous portfolio: gamma * new + (1 - gamma) * old."""

    def __init__(self, n, gamma=0.8, alpha=1.5):
        super().__init__(n)
        self.gamma, self.alpha = gamma, alpha
        self.growth = np.ones(n)

    def update(self, x):
        self.growth = self.growth * x
        weights = np.power(np.maximum(self.growth, 1e-10), self.alpha) + 1e-10
        total = np.sum(weights)
        new = weights / total if total > 1e-10 else np.full(self.n, 1.0 / self.n)
        if self.gamma != 1.0:
            new = self.gamma * new + (1 - self.gamma) * self.b
            total = np.sum(new)
            new = new / total if total > 1e-10 else np.full(self.n, 1.0 / self.n)
        self.b = new


class FollowTheRegularizedLeader(Online):
    """The authors' ONS-style FTRL with a ridge term."""

    def __init__(self, n, beta=0.13, delta=0.925, ridge_const=0.015):
        super().__init__(n)
        self.beta, self.delta, self.ridge = beta, delta, ridge_const
        self.A = np.eye(n)
        self.grad_sum = np.zeros(n)

    def update(self, x):
        ret = np.dot(self.b, x)
        self.A = self.A + np.outer(x, x) / (ret + EPS) ** 2 + np.eye(self.n) * self.ridge
        self.grad_sum = self.grad_sum + x / (ret + EPS)
        p = (1 + (1 / self.beta)) * self.grad_sum
        self.b = project_to_simplex(np.linalg.inv(self.A).dot(p) * self.delta)


class AggregationSimple(Online):
    """Weights num_base_portfolios random portfolios by cumulative performance ** learning_rate."""

    def __init__(self, n, learning_rate=0.4, num_base_portfolios=3, seed=0):
        super().__init__(n)
        self.base = np.random.RandomState(seed).dirichlet(np.ones(n), num_base_portfolios)
        self.prior = np.ones(num_base_portfolios) / num_base_portfolios
        self.performance = np.ones(num_base_portfolios)
        self.lr = learning_rate

    def portfolio(self):
        w = self.prior * self.performance ** self.lr
        return (w / np.sum(w)).dot(self.base)

    def update(self, x):
        self.performance = self.performance * self.base.dot(x)


# ---------------------------------------------------------------- follow the loser


class Anticor(Online):
    """The authors' simplified Anticor: compares log price ratios over two consecutive windows
    and moves weight by alpha times the net positive cross-correlation above corr_threshold."""

    def __init__(self, n, window_size=3, alpha=2.5, corr_threshold=0.5):
        super().__init__(n)
        self.w, self.alpha, self.threshold = window_size, alpha, corr_threshold
        self.rows: list[np.ndarray] = []

    def update(self, x):
        self.rows.append(np.asarray(x, dtype=float))
        t, w, n = len(self.rows), self.w, self.n
        if t < 2 * w:
            return
        y1 = np.log(np.array(self.rows[t - 2 * w:t - w]))
        y2 = np.log(np.array(self.rows[t - w:t]))
        mcov = np.cov(y1.T, y2.T)[:n, n:]
        s1, s2 = np.std(y1, axis=0), np.std(y2, axis=0)
        s1[s1 == 0] = 1e-10
        s2[s2 == 0] = 1e-10
        mcor = mcov / np.outer(s1, s2)
        pos = np.where(mcor > self.threshold, mcor, 0)
        transfer = (np.sum(pos, axis=0) - np.sum(pos, axis=1)) * self.alpha
        new = np.maximum(self.b + transfer, 0)
        if np.sum(new) > 0:
            new = new / np.sum(new)
        self.b = new


class PAMRAuthors(Online):
    """The authors' PAMR (clipped to non-negative and renormalized rather than projected)."""

    def __init__(self, n, epsilon=0.9, C=10.0):
        super().__init__(n)
        self.epsilon, self.C = epsilon, C

    def update(self, x):
        ret = np.dot(self.b, x)
        diff = x - np.mean(x)
        denom = np.linalg.norm(diff) ** 2
        tau = min(self.C, max(0.0, (ret - self.epsilon) / (denom + EPS))) if denom > 0 else 0.0
        new = np.maximum(self.b - tau * diff, 0)
        if np.sum(new) > 0:
            new = new / np.sum(new)
        self.b = new


class CWMRAuthors(Online):
    """The authors' simplified CWMR (no confidence term in the step size, a learning-rate
    factor eta, no mean-centering)."""

    def __init__(self, n, epsilon=0.89, theta=0.92, eta=0.93):
        super().__init__(n)
        self.epsilon, self.theta, self.eta = epsilon, theta, eta
        self.sigma = np.eye(n)

    def update(self, x):
        mean = np.dot(self.b, x)
        denom = x @ (self.sigma @ x)
        lam = self.eta * max(0, (mean - self.epsilon) / (denom + EPS)) if denom > 0 else 0.0
        mu = self.b - lam * (self.sigma @ x)
        inv = np.linalg.inv(self.sigma + np.eye(self.n) * 1e-12)
        inv += 2 * lam * self.theta * np.outer(x, x)
        self.sigma = np.linalg.inv(inv)
        self.b = project_to_simplex(mu)


class OLMARAuthors(Online):
    """The authors' OLMAR: averages past price ratios and updates only when the predicted
    return falls below epsilon. With the paper's epsilon = 0.8 it never updates (CRP)."""

    def __init__(self, n, window_size=2, epsilon=0.8, eta=20):
        super().__init__(n)
        self.w, self.epsilon, self.eta = window_size, epsilon, eta
        self.rows: list[np.ndarray] = []

    def update(self, x):
        self.rows.append(np.asarray(x, dtype=float))
        t = len(self.rows)
        window = self.rows[:t] if t < self.w else self.rows[t - self.w:t]
        predicted = np.mean(window, axis=0)
        m = np.dot(self.b, predicted)
        if m < self.epsilon:
            tau = (self.epsilon - m) / (np.dot(predicted, predicted) + EPS)
            self.b = project_to_simplex(self.b + self.eta * tau * (predicted - self.b))


class RMR(Online):
    """The authors' robust median reversion: L1-median of the last window_size price ratios
    divided by the latest ratio (Huang et al. use prices over the current price)."""

    def __init__(self, n, window_size=8, epsilon=1.1, eta=30):
        super().__init__(n)
        self.w, self.epsilon, self.eta = window_size, epsilon, eta
        self.rows: list[np.ndarray] = []

    def update(self, x):
        self.rows.append(np.asarray(x, dtype=float))
        t = len(self.rows)
        window = self.rows[:t] if t < self.w else self.rows[t - self.w:t]
        mu = l1_median(np.array(window, dtype=np.float64))
        predicted = mu / (self.rows[t - 1] + EPS)
        m = np.dot(self.b, predicted)
        if m < self.epsilon:
            tau = (self.epsilon - m) / (np.dot(predicted, predicted) + EPS)
            self.b = project_to_simplex(self.b + self.eta * tau * (predicted - self.b))


# ---------------------------------------------------------------- pattern matching

BINS = ((0.0, 0.5), (0.5, 1.0), (1.0, 1.5))


def _window_means(rows: np.ndarray, w: int) -> np.ndarray:
    """Means of rows[i-w:i] for i = w..len(rows), one row each."""
    c = np.cumsum(np.vstack([np.zeros(rows.shape[1]), rows]), axis=0)
    return (c[w:] - c[:-w]) / w


def _bin(value: float, bins) -> int:
    return next((k for k, (lo, hi) in enumerate(bins) if lo <= value < hi), -1)


def select_histogram(rows, w=4, bins=BINS, **_):
    n = len(rows)
    if n < w:
        return []
    means = _window_means(rows, w).mean(axis=1)
    latest = _bin(means[-1], bins)
    return [i + w for i in range(len(means) - 1) if _bin(means[i], bins) == latest]


def select_kernel(rows, w=5, threshold=0.1, **_):
    n = len(rows)
    if n < w:
        return []
    means = _window_means(rows, w)
    dist = np.linalg.norm(means[:-1] - means[-1], axis=1)
    return [int(i) + w for i in np.nonzero(dist <= threshold / np.sqrt(w))[0]]


def select_nearest(rows, w=3, num_neighbors=5, **_):
    n = len(rows)
    if n < w:
        return []
    means = _window_means(rows, w)
    dist = np.linalg.norm(means[:-1] - means[-1], axis=1)
    order = np.argsort(dist, kind="stable")[:num_neighbors]
    return [int(i) + w for i in order]


def select_correlation(rows, w=3, rho=0.6, **_):
    n = len(rows)
    if n < w:
        return []
    means = _window_means(rows, w)
    latest = means[-1]
    out = []
    for i in range(len(means) - 1):
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(latest, means[i])[0, 1]
        if corr >= rho:
            out.append(i + w)
    return out


def _optimize(objective, m):
    cons = ({"type": "eq", "fun": lambda b: np.sum(b) - 1},)
    return minimize(objective, np.ones(m) / m, method="SLSQP", bounds=[(0, 1)] * m,
                    constraints=cons).x


def optimize_log(C, rows, **_):
    m = rows.shape[1]
    if not C:
        return np.ones(m) / m
    xc = rows[C]
    return _optimize(lambda b: -np.sum(np.log(np.dot(xc, b) + EPS)) / len(C), m)


def optimize_semi_log(C, rows, **_):
    m = rows.shape[1]
    if not C:
        return np.ones(m) / m
    xc = rows[C]

    def f(z):
        return z - 0.5 * (z - 1) ** 2

    return _optimize(lambda b: -np.sum(f(np.dot(xc, b))) / len(C), m)


def optimize_markowitz(C, rows, lambda_=0.7, **_):
    m = rows.shape[1]
    if not C:
        return np.ones(m) / m
    xc = rows[C]
    mean, cov = np.mean(xc, axis=0), np.cov(xc, rowvar=False)
    return _optimize(lambda b: -np.dot(b, mean) + lambda_ * b.T.dot(cov).dot(b), m)


SELECTIONS = {"histogram": select_histogram, "kernel": select_kernel,
              "nearest_neighbor": select_nearest, "correlation": select_correlation}
OPTIMIZERS = {"log_optimal": optimize_log, "semi_log_optimal": optimize_semi_log,
              "markowitz": optimize_markowitz}


class PatternMatching(Online):
    """Finds past days whose preceding window of price ratios resembles the latest window, then
    picks the portfolio that would have done best on the days that followed them."""

    def __init__(self, n, selection="histogram", optimizer="semi_log_optimal", w=4,
                 threshold=0.1, num_neighbors=3, rho=0.6, lambda_=0.7):
        super().__init__(n)
        if selection not in SELECTIONS or optimizer not in OPTIMIZERS:
            raise ValueError(f"selection must be one of {sorted(SELECTIONS)} and optimizer one "
                             f"of {sorted(OPTIMIZERS)}")
        self.select, self.opt = SELECTIONS[selection], OPTIMIZERS[optimizer]
        self.kw = {"w": w, "threshold": threshold, "num_neighbors": num_neighbors, "rho": rho,
                   "lambda_": lambda_}
        self.w = w
        self.rows = np.empty((0, n))

    def update(self, x):
        self.rows = np.vstack([self.rows, x])
        t = len(self.rows)
        try:
            C = self.select(self.rows, **self.kw) if t >= self.w else []
            b = self.opt(C, self.rows, **self.kw)
            if np.any(np.isnan(b)):
                b = np.full(self.n, 1.0 / self.n)
            elif not np.isclose(np.sum(b), 1.0, rtol=1e-5):
                b = b / np.sum(b)
        except Exception:
            # The authors fall back to equal weights on any optimizer failure.
            b = np.full(self.n, 1.0 / self.n)
        self.b = b


# ---------------------------------------------------------------- meta-learning


class AggregationAlgorithm(Online):
    """Exponential weights on the assets themselves, mixed with uniform by gamma. At the paper's
    settings (learning_rate 0.005, gamma 0.3) the weights stay within a hair of equal, which is
    why the paper reports it almost identical to CRP (12.1514 against 12.1584)."""

    def __init__(self, n, learning_rate=0.005, gamma=0.3):
        super().__init__(n)
        self.lr, self.gamma = learning_rate, gamma
        self.weights = np.ones(n) / n

    def portfolio(self):
        return self.weights / np.sum(self.weights)

    def update(self, x):
        w = self.weights / np.sum(self.weights)
        w = w * np.exp(-self.lr * -np.log(x + EPS))
        self.weights = (1 - self.gamma) * w + self.gamma * (np.ones(self.n) / self.n)


def _weighted_majority(portfolios, weights, x, learning_rate):
    returns = np.maximum(np.einsum("mn,n->m", portfolios, x), 1e-10)
    w = weights * np.exp(-learning_rate * -np.log(returns))
    total = np.sum(w)
    return w / total if total > 1e-10 else np.ones_like(w) / len(w)


class FollowTheLeadingHistory(Online):
    """Spawns an online Newton step expert every session, combines them by weighted majority,
    and drops experts whose weight falls below drop_threshold."""

    def __init__(self, n, eta=0.35, learning_rate=0.07, drop_threshold=0.55):
        super().__init__(n)
        self.eta, self.lr, self.drop = eta, learning_rate, drop_threshold
        self.experts: list[list[np.ndarray]] = []   # [portfolio, A]
        self.weights = np.array([])

    def _spawned(self):
        experts = self.experts + [[np.full(self.n, 1.0 / self.n), np.eye(self.n) * 1e-2]]
        if len(self.weights) == 0:
            weights = np.array([1.0])
        else:
            weights = np.append(self.weights, [1.0])
            weights = weights / np.sum(weights)
        return experts, weights

    def portfolio(self):
        experts, weights = self._spawned()
        p = np.dot(weights, np.array([e[0] for e in experts]))
        return p / np.sum(p)

    def update(self, x):
        experts, weights = self._spawned()
        portfolios = np.array([e[0] for e in experts])
        weights = _weighted_majority(portfolios, weights, x, self.lr)
        for e in experts:
            ret = max(np.dot(e[0], x), 1e-10)
            grad = -x / ret
            e[1] = e[1] + np.outer(grad, grad)
            a_inv = np.linalg.inv(e[1] + np.eye(self.n) * 1e-8)
            e[0] = project_to_simplex(e[0] - (1.0 / self.eta) * a_inv.dot(grad))
        keep = np.where(weights >= self.drop)[0]
        if len(keep) == 0 and len(weights) > 0:
            keep = np.array([np.argmax(weights)])
        self.experts = [experts[i] for i in keep]
        weights = weights[keep]
        self.weights = (weights / weights.sum() if weights.sum() > 0
                        else np.ones(len(self.experts)) / len(self.experts))


EXPERTS = {"cwmr": CWMRAuthors, "ftrl": FollowTheRegularizedLeader, "pamr": PAMRAuthors,
           "rmr": RMR, "olmar": OLMARAuthors}


class MetaExperts(Online):
    """Combines base experts. method "exponential" (the authors' fast universalization and
    online gradient update, which use the same rule) reweights experts by exp(-learning_rate *
    log loss); "newton" (online Newton update) takes a Newton step on the expert weights.
    Each expert keeps its own state from day to day; the authors' code instead re-runs every
    expert over the whole history at each step, starting from its last portfolio."""

    def __init__(self, n, method="exponential", learning_rate=0.01,
                 experts=("cwmr", "ftrl", "pamr")):
        super().__init__(n)
        if method not in ("exponential", "newton"):
            raise ValueError('method must be "exponential" or "newton"')
        self.method, self.lr = method, learning_rate
        self.experts = [EXPERTS[e](n) for e in experts]
        m = len(self.experts)
        self.weights = np.ones(m) / m
        self.a_inv = np.eye(m) / 1e-2

    def portfolio(self):
        p = np.dot(self.weights, np.array([e.portfolio() for e in self.experts]))
        total = np.sum(p)
        return p / total if total > 1e-10 else np.full(self.n, 1.0 / self.n)

    def update(self, x):
        portfolios = np.array([e.portfolio() for e in self.experts])
        losses = -np.log(np.maximum(portfolios.dot(x), 1e-10))
        if self.method == "exponential":
            w = self.weights * np.exp(-self.lr * losses)
            total = np.sum(w)
            self.weights = w / total if total > 1e-10 else np.ones(len(w)) / len(w)
        else:
            u = losses.reshape(-1, 1)
            au = self.a_inv @ u
            self.a_inv = self.a_inv - (au @ au.T) / (1.0 + (u.T @ au)[0, 0] + 1e-10)
            step = (1.0 / self.lr) * (self.a_inv @ losses)
            self.weights = project_to_simplex(self.weights - step)
        for e in self.experts:
            e.update(x)


# ---------------------------------------------------------------- btest strategy wrapper


class OnlineStrategy(Strategy):
    """Base for btest strategies built on an `Online` algorithm. Subclasses set universe,
    rebalance and params, implement make(n) to build the algorithm, and define
    `def decide(self, as_of, data): return self.run_online(data)`."""

    def make(self, n: int) -> Online:
        raise NotImplementedError

    def run_online(self, data):
        closes = {s: data.history(s, "close") for s in self.universe}
        live = tuple(s for s, c in closes.items() if len(c) >= 2)
        if len(live) < 2:
            return None
        n = min(len(closes[s]) for s in live)
        rel = np.column_stack([closes[s][-n:][1:] / closes[s][-n:][:-1] for s in live])
        # The last row uses today's price at the cutoff; tomorrow it is replaced by today's
        # close. So the kept state covers completed sessions only, and today's row is applied
        # to a copy.
        done = rel[:-1]
        state = getattr(self, "_online", None)
        if state and state["live"] == live and state["rows"] == len(done) - 1:
            algo = state["algo"]
            algo.update(done[-1])
        elif state and state["live"] == live and state["rows"] == len(done):
            algo = state["algo"]
        else:
            algo = self.make(len(live))
            for x in done:
                algo.update(x)
        self._online = {"live": live, "rows": len(done), "algo": algo}
        today = copy.deepcopy(algo)
        today.update(rel[-1])
        b = today.portfolio()
        return {s: float(w) for s, w in zip(live, b) if w > 1e-6}
