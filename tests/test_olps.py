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


# Markowitz on a single matched day takes np.cov of one row, which is NaN in both
# implementations; the test checks they agree, so the warning is expected.
@pytest.mark.filterwarnings("ignore:Degrees of freedom:RuntimeWarning",
                            "ignore:invalid value encountered:RuntimeWarning",
                            "ignore:divide by zero encountered:RuntimeWarning")
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


class MonthlyExample(Example):
    bars = "monthly"
    rebalance = "month_end"


def test_monthly_bars_use_month_end_closes_and_cache_equals_replay():
    sessions = nyse_sessions(date(2023, 1, 3), date(2024, 6, 28))
    dates = sessions["date"].to_list()
    rel = prices(T=len(dates), N=3, sd=0.015, seed=4)
    frames = {}
    for k, s in enumerate(Example.universe):
        close = 100 * np.cumprod(rel[:, k])
        frames[s] = pl.DataFrame({
            "date": dates, **{c: close for c in ("open", "high", "low", "close", "raw_close",
                                                 "fill", "cut_open", "cut_high", "cut_low",
                                                 "cut_close", "raw_cut_close")},
            "volume": np.full(len(dates), 1e6), "cut_volume": np.full(len(dates), 5e5)})
    engine = PortfolioEngine(Market(dates, frames), sessions, PortfolioConfig())
    month_ends = [i for i in range(len(dates) - 1) if dates[i + 1].month != dates[i].month]
    cached, fresh = MonthlyExample(), MonthlyExample()
    for i in month_ends[2:]:
        a = cached.decide(engine.decide_ts[i], Data(engine, i))
        fresh.__dict__.pop("_online", None)
        b = fresh.decide(engine.decide_ts[i], Data(engine, i))
        assert max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)) < 1e-12
    # The algorithm saw one ratio per month: replaying month-end closes directly agrees.
    last = month_ends[-1]
    me = [i for i in month_ends if i < last] + [last]
    closes = np.column_stack([frames[s]["close"].to_numpy()[me] for s in Example.universe])
    algo = olps.FollowTheRegularizedLeader(3)
    for x in closes[1:] / closes[:-1]:
        algo.update(x)
    expected = dict(zip(Example.universe, algo.portfolio()))
    assert all(abs(a[k] - expected[k]) < 1e-12 for k in a)


class MonthlyTradingExample(Example):
    rebalance = "month_end"


def test_skipped_sessions_are_caught_up_identically():
    sessions = nyse_sessions(date(2023, 1, 3), date(2023, 12, 29))
    dates = sessions["date"].to_list()
    rel = prices(T=len(dates), N=3, sd=0.015, seed=8)
    frames = {}
    for k, s in enumerate(Example.universe):
        close = 100 * np.cumprod(rel[:, k])
        frames[s] = pl.DataFrame({
            "date": dates, **{c: close for c in ("open", "high", "low", "close", "raw_close",
                                                 "fill", "cut_open", "cut_high", "cut_low",
                                                 "cut_close", "raw_cut_close")},
            "volume": np.full(len(dates), 1e6), "cut_volume": np.full(len(dates), 5e5)})
    engine = PortfolioEngine(Market(dates, frames), sessions, PortfolioConfig())
    cached, fresh = MonthlyTradingExample(), MonthlyTradingExample()
    for i in range(5, len(dates), 17):
        a = cached.decide(engine.decide_ts[i], Data(engine, i))
        fresh.__dict__.pop("_online", None)
        b = fresh.decide(engine.decide_ts[i], Data(engine, i))
        assert max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)) < 1e-12


class WeeklyExample(Example):
    bars = "weekly"
    rebalance = "weekly"


def test_weekly_bars_use_week_end_closes_and_cache_equals_replay():
    sessions = nyse_sessions(date(2023, 11, 1), date(2024, 3, 28))
    dates = sessions["date"].to_list()
    rel = prices(T=len(dates), N=3, sd=0.015, seed=5)
    frames = {}
    for k, s in enumerate(Example.universe):
        close = 100 * np.cumprod(rel[:, k])
        frames[s] = pl.DataFrame({
            "date": dates, **{c: close for c in ("open", "high", "low", "close", "raw_close",
                                                 "fill", "cut_open", "cut_high", "cut_low",
                                                 "cut_close", "raw_cut_close")},
            "volume": np.full(len(dates), 1e6), "cut_volume": np.full(len(dates), 5e5)})
    engine = PortfolioEngine(Market(dates, frames), sessions, PortfolioConfig())
    week_ends = [i for i in range(len(dates) - 1)
                 if dates[i + 1].isocalendar()[:2] != dates[i].isocalendar()[:2]]
    cached, fresh = WeeklyExample(), WeeklyExample()
    for i in week_ends[2:]:
        a = cached.decide(engine.decide_ts[i], Data(engine, i))
        fresh.__dict__.pop("_online", None)
        b = fresh.decide(engine.decide_ts[i], Data(engine, i))
        assert max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)) < 1e-12
    # Spans New Year 2024, where ISO week 1 starts on 2024-01-01.
    last = week_ends[-1]
    we = [i for i in week_ends if i < last] + [last]
    closes = np.column_stack([frames[s]["close"].to_numpy()[we] for s in Example.universe])
    algo = olps.FollowTheRegularizedLeader(3)
    for x in closes[1:] / closes[:-1]:
        algo.update(x)
    expected = dict(zip(Example.universe, algo.portfolio()))
    assert all(abs(a[k] - expected[k]) < 1e-12 for k in a)


class LaunchExample(Example):
    def make(self, n):
        return olps.CWMRAuthors(n)


def test_a_symbol_launching_later_joins_without_restarting_the_algorithm():
    sessions = nyse_sessions(date(2023, 1, 3), date(2023, 8, 31))
    dates = sessions["date"].to_list()
    rel = prices(T=len(dates), N=3, sd=0.015, seed=9)
    launch = 60
    frames = {}
    for k, s in enumerate(Example.universe):
        close = 100 * np.cumprod(rel[:, k])
        lo = launch if s == "C" else 0
        frames[s] = pl.DataFrame({
            "date": dates[lo:], **{c: close[lo:] for c in (
                "open", "high", "low", "close", "raw_close", "fill", "cut_open", "cut_high",
                "cut_low", "cut_close", "raw_cut_close")},
            "volume": np.full(len(dates) - lo, 1e6), "cut_volume": np.full(len(dates) - lo, 5e5)})
    engine = PortfolioEngine(Market(dates, frames), sessions, PortfolioConfig())
    cached, fresh = LaunchExample(), LaunchExample()
    held_c = False
    for i in range(2, len(dates)):
        a = cached.decide(engine.decide_ts[i], Data(engine, i))
        fresh.__dict__.pop("_online", None)
        b = fresh.decide(engine.decide_ts[i], Data(engine, i))
        assert max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)) < 1e-12
        assert sum(a.values()) == pytest.approx(1.0)
        # C needs two prices for a ratio, so it can first be held the session after launch.
        if i <= launch:
            assert "C" not in a
        held_c |= "C" in a
    assert held_c
    # Replaying by hand: before C trades, its ratio is the mean of A's and B's, and the weight
    # the algorithm gives C is split equally between them.
    last = len(dates) - 1
    x = 100 * np.cumprod(rel, axis=0)
    r = x[1:last + 1] / x[:last]
    r[:launch, 2] = r[:launch, :2].mean(axis=1)
    algo = olps.CWMRAuthors(3)
    for row in r:
        algo.update(row)
    expected = dict(zip(Example.universe, algo.portfolio()))
    assert all(abs(a[k] - expected[k]) < 1e-12 for k in a)
    # Before launch, C's share goes to A and B equally.
    split = 0
    for i in range(2, launch):
        a = LaunchExample().decide(engine.decide_ts[i], Data(engine, i))
        algo = olps.CWMRAuthors(3)
        for row in r[:i]:
            algo.update(row)
        b = algo.portfolio()
        assert a.get("A", 0) == pytest.approx(b[0] + b[2] / 2, abs=1e-6)
        assert a.get("B", 0) == pytest.approx(b[1] + b[2] / 2, abs=1e-6)
        split += b[2] > 0.01
    assert split
