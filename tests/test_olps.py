from datetime import date

import numpy as np
import polars as pl
import pytest

from btest import olps
from btest.calendar import nyse_sessions
from btest.portfolio import Data, Market, PortfolioConfig, PortfolioEngine
from tests import olps_reference as ref


def prices(T=90, N=6, sd=0.02, seed=3):
    rng = np.random.default_rng(seed)
    return np.exp(rng.normal(0.0003, sd, size=(T, N)))


def run_online(algo, rel):
    """Portfolios in the authors' layout: row 0 is the start, row t follows rows 0..t-1."""
    out = [algo.portfolio().copy()]
    for t in range(1, len(rel)):
        algo.update(rel[t - 1])
        out.append(algo.portfolio().copy())
    return np.array(out)


def uniform(n):
    return np.full(n, 1.0 / n)


CASES = [
    ("ExponentialGradient", lambda n: olps.ExponentialGradient(n, smoothing=0.7),
     lambda rel: ref.exponential_gradient(uniform(rel.shape[1]), rel, smoothing=0.7)),
    ("FollowTheLeader", lambda n: olps.FollowTheLeader(n),
     lambda rel: ref.follow_the_leader(uniform(rel.shape[1]), rel)),
    ("FollowTheRegularizedLeader", lambda n: olps.FollowTheRegularizedLeader(n),
     lambda rel: ref.follow_the_regularized_leader(uniform(rel.shape[1]), rel)),
    ("Anticor", lambda n: olps.Anticor(n),
     lambda rel: ref.anticor(uniform(rel.shape[1]), rel)),
    ("PAMRAuthors", lambda n: olps.PAMRAuthors(n),
     lambda rel: ref.pamr(uniform(rel.shape[1]), rel)),
    ("CWMRAuthors", lambda n: olps.CWMRAuthors(n),
     lambda rel: ref.cwmr(uniform(rel.shape[1]), rel)),
    ("OLMARAuthors", lambda n: olps.OLMARAuthors(n, epsilon=1.02),
     lambda rel: ref.olmar(uniform(rel.shape[1]), rel, epsilon=1.02)),
    ("RMR", lambda n: olps.RMR(n),
     lambda rel: ref.rmr(uniform(rel.shape[1]), rel)),
    ("AggregationAlgorithm", lambda n: olps.AggregationAlgorithm(n, learning_rate=2.0, gamma=0.05),
     lambda rel: ref.aggregation_algorithm_generalized(uniform(rel.shape[1]), rel,
                                                       learning_rate=2.0, gamma=0.05)),
    ("FollowTheLeadingHistory", lambda n: olps.FollowTheLeadingHistory(n),
     lambda rel: ref.follow_the_leading_history(uniform(rel.shape[1]), rel)),
]


@pytest.mark.parametrize("name,ours,theirs", CASES, ids=[c[0] for c in CASES])
def test_matches_the_authors_code(name, ours, theirs):
    rel = prices()
    expected = np.asarray(theirs(rel))
    got = run_online(ours(rel.shape[1]), rel)
    assert np.abs(got - expected).max() < 1e-8
    # The comparison only means something if the algorithm moved away from equal weights.
    assert np.abs(got - uniform(rel.shape[1])).max() > 1e-4


def test_seeded_random_portfolios_match_the_authors_code_with_the_same_seed():
    rel = prices()
    n = rel.shape[1]
    np.random.seed(5)
    expected = ref.universal_portfolios(uniform(n), rel)
    assert np.abs(run_online(olps.UniversalPortfolios(n, seed=5), rel) - expected).max() < 1e-10
    np.random.seed(5)
    expected = ref.aggregation_based_simple(uniform(n), rel)
    assert np.abs(run_online(olps.AggregationSimple(n, seed=5), rel) - expected).max() < 1e-10


SELECT = {"histogram": ref.histogram_based_selection, "kernel": ref.kernel_based_selection,
          "nearest_neighbor": ref.nearest_neighbor_selection,
          "correlation": ref.correlation_based_selection}
OPTIM = {"log_optimal": ref.log_optimal_portfolio,
         "semi_log_optimal": ref.semi_log_optimal_portfolio,
         "markowitz": ref.markowitz_portfolio}


@pytest.mark.parametrize("selection", list(SELECT))
@pytest.mark.parametrize("optimizer", list(OPTIM))
def test_pattern_matching_matches_the_authors_code(selection, optimizer):
    rel = prices(T=40, N=4, sd=0.03)
    kw = {"w": 3, "threshold": 0.05, "num_neighbors": 4, "rho": 0.2, "lambda_": 0.7}
    expected = ref.pattern_matching_portfolio_master(
        uniform(4), rel, methods={"sample_selection": SELECT[selection],
                                  "portfolio_optimization": OPTIM[optimizer]}, **kw)
    got = run_online(olps.PatternMatching(4, selection=selection, optimizer=optimizer, **kw), rel)
    assert np.abs(got - expected).max() < 1e-6
    assert np.abs(got - 0.25).max() > 1e-3


def test_degenerate_settings_from_the_paper_reduce_to_equal_weights():
    rel = prices()
    n = rel.shape[1]
    assert np.allclose(run_online(olps.ExponentialGradient(n, smoothing=0.0), rel), uniform(n))
    assert np.allclose(run_online(olps.OLMARAuthors(n), rel), uniform(n))


def test_meta_experts_combine_their_experts():
    rel = prices()
    n = rel.shape[1]
    for method in ("exponential", "newton"):
        b = run_online(olps.MetaExperts(n, method=method), rel)
        assert np.allclose(b.sum(axis=1), 1.0) and (b >= -1e-12).all()


class Example(olps.OnlineStrategy):
    universe = ["A", "B", "C"]
    rebalance = "daily"
    params = {}

    def make(self, n):
        return olps.FollowTheRegularizedLeader(n)

    def decide(self, as_of, data):
        return self.run_online(data)


def test_strategy_wrapper_cache_equals_full_replay():
    sessions = nyse_sessions(date(2024, 1, 2), date(2024, 6, 28))
    dates = sessions["date"].to_list()
    rel = prices(T=len(dates), N=3, sd=0.015, seed=9)
    frames = {}
    for k, s in enumerate(Example.universe):
        close = 100 * np.cumprod(rel[:, k])
        cut = close * (1 + 0.002 * np.sin(np.arange(len(dates))))
        frames[s] = pl.DataFrame({
            "date": dates, **{c: close for c in ("open", "high", "low", "close", "raw_close",
                                                 "fill")},
            **{c: cut for c in ("cut_open", "cut_high", "cut_low", "cut_close", "raw_cut_close")},
            "volume": np.full(len(dates), 1e6), "cut_volume": np.full(len(dates), 5e5)})
    engine = PortfolioEngine(Market(dates, frames), sessions, PortfolioConfig())
    cached, fresh = Example(), Example()
    worst = 0.0
    for i in range(3, len(dates)):
        a = cached.decide(engine.decide_ts[i], Data(engine, i))
        fresh.__dict__.pop("_online", None)
        b = fresh.decide(engine.decide_ts[i], Data(engine, i))
        worst = max(worst, max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)))
    assert worst < 1e-12
