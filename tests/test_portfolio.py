from datetime import date, timedelta

import polars as pl
import pytest

from btest import daily, store
from btest.calendar import nyse_sessions
from btest.daily import Timing
from btest.portfolio import (Market, PortfolioConfig, PortfolioCosts, PortfolioEngine, Targets,
                             is_decision_day, occ_symbol, parse_occ)
from btest.strategy import Strategy, has_decide

FREE = PortfolioConfig(cash=10_000.0, costs=PortfolioCosts(slippage_bps=0.0, sec_fee_rate=0.0,
                                                           option_half_spread=0.0,
                                                           option_min_half_spread=0.0),
                       cash_yield=False)
SESSIONS = nyse_sessions(date(2024, 1, 2), date(2024, 3, 29))
DATES = SESSIONS["date"].to_list()


def frame(closes, cut=None, fill=None):
    """Daily rows; cut_close and fill default to the close."""
    n = len(closes)
    cut = cut or closes
    fill = fill or closes
    return pl.DataFrame({
        "date": DATES[:n], "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1e6] * n, "cut_open": cut, "cut_high": cut, "cut_low": cut,
        "cut_close": cut, "cut_volume": [5e5] * n, "raw_cut_close": cut, "raw_close": closes,
        "fill": fill,
    })


def engine(frames, config=FREE, options=None, rates=None):
    n = max(f.height for f in frames.values())
    return PortfolioEngine(Market(DATES[:n], frames), SESSIONS, config, rates=rates,
                           options=options)


class Script(Strategy):
    """Returns the targets given per session index and records what it saw."""

    params = {"plan": {}}
    universe = ["A", "B"]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seen = []
        self.i = -1

    def decide(self, as_of, data):
        self.i += 1
        self.seen.append((as_of, data.history("A")[-1], data.cash))
        return self.params["plan"].get(self.i)


def run(strategy, frames, config=FREE, n=None, **kw):
    e = engine(frames, config, **kw)
    end = DATES[n] if n else DATES[-1]
    return e, e.run(strategy, DATES[0], end)


def test_decision_sees_cutoff_price_and_fills_at_fill_bar():
    a = frame([10.0, 11.0, 12.0], cut=[9.5, 10.5, 11.5], fill=[9.8, 10.8, 11.8])
    s = Script(plan={0: {"A": 1.0}})
    e, res = run(s, {"A": a}, n=3)
    as_of, seen_close, _ = s.seen[0]
    assert seen_close == 9.5
    assert as_of == SESSIONS["close_utc"][0] - timedelta(minutes=30)
    [f] = res.fills
    assert f.price == 9.8
    assert f.ts == SESSIONS["close_utc"][0] - timedelta(minutes=15)
    # A $10,000 notional order bought at the 9.8 fill price.
    assert f.qty == pytest.approx(10_000 / 9.8)
    assert has_decide(Script)


def test_rotation_sells_before_buying_with_all_cash_in_use():
    a = frame([10.0, 10.0, 10.0])
    b = frame([20.0, 20.0, 20.0])
    s = Script(plan={0: {"A": 1.0}, 1: {"B": 1.0}})
    e, res = run(s, {"A": a, "B": b}, n=3)
    assert [f.symbol for f in res.fills] == ["A", "A", "B"]
    assert e.account.qty("A") == 0
    assert e.account.qty("B") == pytest.approx(500.0)
    assert e.account.cash == pytest.approx(0.0, abs=1e-6)


def test_whole_shares_when_fractional_is_off():
    a = frame([30.0, 30.0])
    s = Script(plan={0: {"A": 1.0}})
    e, res = run(s, {"A": a}, PortfolioConfig(cash=1_000.0, costs=FREE.costs, fractional=False,
                                              cash_yield=False), n=2)
    assert res.fills[0].qty == 33
    assert e.account.cash == pytest.approx(10.0)


def test_cash_earns_the_tbill_rate_between_sessions():
    a = frame([10.0] * 3)
    rates = pl.DataFrame({"date": [date(2023, 12, 29)], "rate": [5.0]})
    cfg = PortfolioConfig(cash=10_000.0, costs=FREE.costs, cash_yield=True)
    e, res = run(Script(), {"A": a}, cfg, n=3, rates=rates)
    days = (DATES[2] - DATES[0]).days
    assert e.account.cash == pytest.approx(10_000 * (1 + 0.05 / 365) ** days, rel=1e-9)


def test_month_end_schedule():
    i = DATES.index(date(2024, 1, 31))
    assert is_decision_day(DATES, i, "month_end")
    assert not is_decision_day(DATES, i - 1, "month_end")
    assert is_decision_day(DATES, i + 1, "month_start")


class FakeOptions:
    def __init__(self, prices):
        self.prices = prices

    def expiries(self, underlying):
        return []

    def chain(self, *a):
        raise NotImplementedError

    def reference(self, symbol, cutoff):
        return self.prices.get(symbol)

    def fills_at(self, symbol, fill_ts, limit, delta):
        return symbol in self.prices

    def mark(self, symbol, ts):
        return self.prices.get(symbol)


class WritePut(Strategy):
    params = {"occ": "", "contracts": 1}
    universe = ["A"]

    def decide(self, as_of, data):
        if data.option_positions() or data.positions():
            return None
        return Targets(options={self.params["occ"]: -self.params["contracts"]})


def test_written_put_is_cash_secured_and_assigned_in_the_money():
    occ = occ_symbol("A", DATES[2], "P", 50.0)
    assert parse_occ(occ).strike == 50.0
    a = frame([55.0, 52.0, 45.0, 46.0])
    e, res = run(WritePut(occ=occ, contracts=3), {"A": a}, n=4,
                 options=FakeOptions({occ: 1.0}))
    # $10,000 secures one $5,000 put twice over, not three times.
    sold = res.fills[0]
    assert (sold.symbol, sold.qty, sold.price) == (occ, -2, 1.0)
    assigned = [f for f in res.fills if f.symbol == "A"]
    assert assigned[0].qty == 200 and assigned[0].price == 50.0
    assert e.account.qty("A") == 200
    assert e.account.cash == pytest.approx(10_000 + 200 - 10_000)


def test_written_put_expires_worthless_out_of_the_money():
    occ = occ_symbol("A", DATES[1], "P", 50.0)
    a = frame([55.0, 56.0, 57.0])
    e, res = run(WritePut(occ=occ), {"A": a}, n=3, options=FakeOptions({occ: 0.5}))
    assert e.account.qty("A") == 0
    assert not e.account.options
    assert e.account.cash == pytest.approx(10_050.0)
    assert res.fills[-1].realized_pnl == pytest.approx(50.0)


def test_raw_daily_uses_cutoff_and_fill_bar_including_half_days(tmp_path):
    sessions = nyse_sessions(date(2024, 7, 2), date(2024, 7, 3))
    rows = []
    for d, close in zip(sessions["date"], sessions["close_utc"]):
        open_ = close - timedelta(hours=6, minutes=30) if d.day == 2 else close - timedelta(
            hours=3, minutes=30)
        t = open_
        k = 0
        while t < close:
            rows.append((t, float(k), float(k) + 0.5, float(k) - 0.5, float(k), 10, 1, float(k),
                         True))
            t += timedelta(minutes=1)
            k += 1
    bars = pl.DataFrame(rows, schema={"ts": pl.Datetime("us", "UTC"), "open": pl.Float64,
                                      "high": pl.Float64, "low": pl.Float64,
                                      "close": pl.Float64, "volume": pl.Int64,
                                      "trades": pl.Int64, "vwap": pl.Float64,
                                      "regular": pl.Boolean}, orient="row")
    store.write_bars(tmp_path, "X", bars)
    out = daily.raw_daily(tmp_path, "X", sessions, Timing())
    full, half = out.row(0, named=True), out.row(1, named=True)
    # Full day: 390 bars; cutoff bar is the one starting 15:14 (index 344), fill 15:45 (375).
    assert (full["cut_close"], full["fill"], full["close"]) == (344.0, 375.0, 389.0)
    # July 3 closes at 13:00: cutoff 12:14 (index 164), fill 12:45 (index 195).
    assert (half["cut_close"], half["fill"], half["close"]) == (164.0, 195.0, 209.0)


def test_daily_cache_rebuilds_when_built_from_a_shorter_calendar(tmp_path):
    sessions = nyse_sessions(date(2024, 7, 1), date(2024, 7, 2))
    rows = [(close - timedelta(minutes=m), 1.0, 1.0, 1.0, 1.0, 10, 1, 1.0, True)
            for close in sessions["close_utc"] for m in range(1, 60)]
    bars = pl.DataFrame(rows, schema={"ts": pl.Datetime("us", "UTC"), "open": pl.Float64,
                                      "high": pl.Float64, "low": pl.Float64,
                                      "close": pl.Float64, "volume": pl.Int64,
                                      "trades": pl.Int64, "vwap": pl.Float64,
                                      "regular": pl.Boolean}, orient="row").sort("ts")
    store.write_bars(tmp_path, "X", bars)
    short = daily.cached_raw_daily(tmp_path, "X", sessions.head(1), Timing())
    assert short["date"].to_list() == [date(2024, 7, 1)]
    full = daily.cached_raw_daily(tmp_path, "X", sessions, Timing())
    assert full["date"].to_list() == [date(2024, 7, 1), date(2024, 7, 2)]


def test_a_day_without_trades_skips_that_symbol_instead_of_poisoning_cash():
    a = frame([10.0, 10.0, 10.0])
    b = frame([20.0, 20.0, 20.0])
    gap = b.with_columns(pl.when(pl.col("date") == DATES[1]).then(None).otherwise(pl.col(c))
                         .alias(c) for c in ("close", "cut_close", "raw_cut_close", "raw_close",
                                             "fill"))
    s = Script(plan={0: {"A": 1.0}, 1: {"B": 1.0}})
    e, res = run(s, {"A": a, "B": gap}, n=3)
    assert not any(f.symbol == "B" for f in res.fills)
    assert res.equity["equity"].is_nan().sum() == 0
    # A was dropped from the targets, so it was sold; B waits for a day it trades.
    assert e.account.cash == pytest.approx(10_000.0)


def test_cash_in_lieu_after_a_split_uses_the_post_split_price():
    from btest.sources.base import Split
    a = frame([100.0, 100.0 / 1.5, 100.0 / 1.5])
    cfg = PortfolioConfig(cash=300.0, costs=FREE.costs, fractional=False, cash_yield=False)
    e = PortfolioEngine(Market(DATES[:3], {"A": a}), SESSIONS, cfg,
                        splits={"A": [Split(DATES[1], 2.0, 3.0, "x")]})
    res = e.run(Script(plan={0: {"A": 1.0}}), DATES[0], DATES[3])
    # 3 shares become 4.5: 4 kept, half a share paid at $66.67, so no value appears or vanishes.
    assert e.account.qty("A") == 4
    assert res.equity["equity"][-1] == pytest.approx(300.0)


def test_written_calls_need_shares_to_cover_them():
    occ = occ_symbol("A", DATES[3], "C", 60.0)
    a = frame([55.0] * 4)

    class WriteCall(Strategy):
        universe = ["A"]
        params = {}

        def decide(self, as_of, data):
            return None if data.option_positions() else Targets(options={occ: -50})

    e, res = run(WriteCall(), {"A": a}, n=2, options=FakeOptions({occ: 1.0}))
    assert not e.account.options and e.account.cash == 10_000.0


def test_month_end_on_a_runs_last_day_uses_the_real_calendar():
    seen = []

    class Watch(Strategy):
        universe = ["A"]
        params = {}

        def decide(self, as_of, data):
            seen.append(data.month_position())

    # The run stops on Jan 9, but January has sessions after it.
    run(Watch(), {"A": frame([10.0] * 6)}, n=6)
    assert seen[-1][1] > 1
