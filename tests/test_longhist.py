from datetime import date

import polars as pl
import pytest

from btest import longhist


def test_build_starts_each_symbol_on_its_first_day_and_fills_gaps(monkeypatch):
    px = {"OLD": pl.DataFrame({"date": [date(1995, 1, 3), date(1995, 1, 5)],
                               "open": [9.5, 10.5], "close": [10.0, 11.0]}),
          "NEW": pl.DataFrame({"date": [date(1995, 1, 5), date(1995, 1, 6)],
                               "open": [19.0, 20.5], "close": [20.0, 21.0]})}
    monkeypatch.setattr(longhist, "yahoo", lambda s: px[s])
    rows = longhist.build(["OLD", "NEW"], date(1995, 1, 9))
    old = rows.filter(pl.col("symbol") == "OLD")
    assert old["date"].to_list() == [date(1995, 1, d) for d in (3, 4, 5, 6)]
    assert old["close"].to_list() == [10.0, 10.0, 11.0, 11.0]
    # A skipped session opens and closes at the previous close.
    assert old["open"].to_list() == [9.5, 10.0, 10.5, 11.0]
    new = rows.filter(pl.col("symbol") == "NEW")
    assert new["date"].to_list() == [date(1995, 1, 5), date(1995, 1, 6)]


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args):
        symbols, end = args
        return type("C", (), {"fetchall": lambda _: [r for r in self.rows
                                                     if r[0] in symbols and r[1] < end]})()


def test_frames_decide_on_the_close_and_fill_at_the_next_open():
    rows = [("SPY", date(1995, 1, 3), 99.0, 100.0), ("SPY", date(1995, 1, 4), 100.5, 101.0),
            ("SPY", date(1995, 1, 5), 101.5, 102.0)]
    f = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 1, 6))["SPY"]
    for c in ("close", "cut_close", "raw_close", "raw_cut_close"):
        assert f[c].to_list() == [100.0, 101.0, 102.0]
    assert f["fill"].to_list() == [100.5, 101.5, None]


def test_an_order_decided_on_a_close_fills_at_the_next_open():
    from btest.calendar import nyse_sessions
    from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
    from btest.strategy import Strategy

    days = nyse_sessions(date(1995, 1, 3), date(1995, 1, 31))
    dates = days["date"].to_list()[:4]
    rows = [("SPY", d, 100.0 + k + 0.5, 100.0 + k) for k, d in enumerate(dates)]
    frames = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 2, 1))

    class Buy(Strategy):
        universe = ["SPY"]
        params = {}

        def decide(self, as_of, data):
            return None if data.position("SPY") else {"SPY": 1.0}

    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.0, sec_fee_rate=0.0),
                          cash_yield=False, data="longhist")
    res = PortfolioEngine(Market(dates, frames), days, cfg).run(Buy(), dates[0], dates[-1])
    assert res.fills[0].price == 101.5  # decided on day 0's close of 100, filled at day 1's open
    # The decision day is marked before the trade, and the fill is stamped at the next open.
    assert res.equity["equity"][0] == cfg.cash
    assert res.fills[0].ts == days["open_utc"][1]


def test_a_decision_on_the_last_session_never_fills_at_its_own_close():
    from btest.calendar import nyse_sessions
    from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
    from btest.strategy import Strategy

    days = nyse_sessions(date(1995, 1, 3), date(1995, 1, 31))
    dates = days["date"].to_list()[:3]
    rows = [("SPY", d, 100.0, 100.0) for d in dates]
    frames = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 2, 1))

    class BuyLast(Strategy):
        universe = ["SPY"]
        params = {}

        def decide(self, as_of, data):
            return {"SPY": 1.0} if as_of.date() == dates[-1] else None

    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.0, sec_fee_rate=0.0),
                          cash_yield=False, data="longhist")
    res = PortfolioEngine(Market(dates, frames), days, cfg).run(BuyLast(), dates[0],
                                                                 date(1995, 2, 1))
    assert res.fills == []


def test_a_queued_order_is_sized_on_decision_day_equity():
    # Overnight interest arrives before the next-open fill; the order still targets what the
    # decision saw, so half of the decision-day equity is invested.
    from btest.calendar import nyse_sessions
    from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
    from btest.strategy import Strategy

    days = nyse_sessions(date(1995, 1, 3), date(1995, 1, 31))
    dates = days["date"].to_list()[:3]
    rows = [("SPY", d, 100.0, 100.0) for d in dates]
    frames = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 2, 1))

    class Half(Strategy):
        universe = ["SPY"]
        params = {}

        def decide(self, as_of, data):
            return None if data.position("SPY") else {"SPY": 0.5}

    rates = pl.DataFrame({"date": [date(1994, 12, 1)], "rate": [10.0]})
    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.0, sec_fee_rate=0.0),
                          data="longhist")
    res = PortfolioEngine(Market(dates, frames), days, cfg, rates=rates).run(
        Half(), dates[0], dates[-1])
    (fill,) = res.fills
    assert fill.qty * fill.price == pytest.approx(cfg.cash * 0.5)


def test_long_history_refuses_splits():
    from btest.calendar import nyse_sessions
    from btest.portfolio import Market, PortfolioConfig, PortfolioEngine
    from btest.sources.base import Split

    days = nyse_sessions(date(1995, 1, 3), date(1995, 1, 31))
    dates = days["date"].to_list()[:2]
    frames = longhist.frames(FakeConn([("SPY", d, 100.0, 100.0) for d in dates]), ["SPY"],
                             date(1995, 2, 1))
    with pytest.raises(ValueError):
        PortfolioEngine(Market(dates, frames), days, PortfolioConfig(data="longhist"),
                        splits={"SPY": [Split(dates[1], 1, 2, "test")]})


def test_open_timing_sees_the_open_and_fills_at_the_close():
    rows = [("SPY", date(1995, 1, 3), 99.0, 100.0), ("SPY", date(1995, 1, 4), 100.5, 101.0)]
    f = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 1, 6), decide_at="open")["SPY"]
    assert f["cut_close"].to_list() == [99.0, 100.5]
    assert f["fill"].to_list() == [100.0, 101.0]
    assert f["close"].to_list() == [100.0, 101.0]


def test_an_order_decided_on_an_open_fills_at_that_sessions_close_not_the_open():
    from btest.calendar import nyse_sessions
    from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
    from btest.strategy import Strategy

    days = nyse_sessions(date(1995, 1, 3), date(1995, 1, 31))
    dates = days["date"].to_list()[:3]
    rows = [("SPY", d, 100.0 + k, 110.0 + k) for k, d in enumerate(dates)]
    frames = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 2, 1), decide_at="open")
    seen = []

    class Buy(Strategy):
        universe = ["SPY"]
        params = {}

        def decide(self, as_of, data):
            seen.append(data.history("SPY", "close")[-1])
            return None if data.position("SPY") else {"SPY": 1.0}

    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.0, sec_fee_rate=0.0),
                          cash_yield=False, data="longhist_open")
    res = PortfolioEngine(Market(dates, frames), days, cfg).run(Buy(), dates[0], date(1995, 2, 1))
    assert seen[0] == 100.0  # the decision saw the open
    (fill,) = res.fills
    assert fill.price == 110.0  # and filled at that session's close
    assert fill.ts == days["close_utc"][0]


def test_week_start_decides_on_each_weeks_first_session():
    from btest.calendar import nyse_sessions
    from btest.portfolio import is_decision_day

    dates = nyse_sessions(date(2024, 12, 23), date(2025, 1, 14))["date"].to_list()
    starts = [d for i, d in enumerate(dates) if is_decision_day(dates, i, "week_start")]
    assert starts == [date(2024, 12, 23), date(2024, 12, 30), date(2025, 1, 6), date(2025, 1, 13)]


def test_slippage_schedule_by_year_and_symbol():
    from btest.portfolio import PortfolioCosts, slippage_bps

    costs = PortfolioCosts(slippage_bps=0.7, slippage_schedule=(
        (1999, 2002, (), 5.0), (2013, 2024, ("SPY",), 1.0), (2013, 2024, (), 2.0)))
    assert slippage_bps(costs, "XBI", 2000) == 5.0
    assert slippage_bps(costs, "SPY", 2020) == 1.0
    assert slippage_bps(costs, "XBI", 2020) == 2.0
    assert slippage_bps(costs, "XBI", 2008) == 0.7


def test_online_strategy_anchored_on_each_weeks_first_open():
    import numpy as np

    from btest.olps import OnlineStrategy

    class Probe(OnlineStrategy):
        universe = ["A"]
        bars, price, anchor = "weekly", "open", "first"

    class FakeData:
        def frame(self, field):
            assert field == "open"
            days = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 13), date(2025, 1, 14),
                    date(2025, 1, 21)]
            return pl.DataFrame({"date": days, "A": [10.0, 11.0, 12.0, 13.0, 14.0]})

    assert np.array_equal(Probe()._closes(FakeData())[:, 0], [10.0, 12.0, 14.0])
