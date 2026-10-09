from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from btest.engine import Config, Costs, Engine
from btest.sources.base import Dividend, Split
from btest.strategy import Strategy

FREE = Config(cash=10_000.0, costs=Costs(slippage_bps=0.0, sec_fee_rate=0.0))


def bars(rows, start=datetime(2024, 1, 2, 14, 30, tzinfo=UTC)):
    """rows: (date_offset_days, raw_open, raw_close[, adjusted_close])"""
    out = []
    for i, r in enumerate(rows):
        day, o, c = r[:3]
        adj = r[3] if len(r) > 3 else c
        ts = start + timedelta(days=day, minutes=i)
        out.append((ts, ts.date(), o, max(o, c), min(o, c), adj, 100.0, o, c))
    return pl.DataFrame(out, schema={
        "ts": pl.Datetime("us", "UTC"), "date": pl.Date, "open": pl.Float64,
        "high": pl.Float64, "low": pl.Float64, "close": pl.Float64, "volume": pl.Float64,
        "raw_open": pl.Float64, "raw_close": pl.Float64,
    }, orient="row")


class Script(Strategy):
    """Places the orders given per bar index and records what it saw."""

    params = {"orders": {}, "method": "order"}

    def on_start(self, ctx):
        self.seen = []
        self.i = 0

    def on_bar(self, ctx, bar):
        self.seen.append((bar.symbol, len(ctx.history(bar.symbol)), ctx.position(bar.symbol)))
        for sym, qty in self.params["orders"].get(self.i, []):
            getattr(ctx, self.params["method"])(sym, qty)
        self.i += 1


def test_order_fills_at_next_bar_open_not_current_close():
    data = {"X": bars([(0, 10, 11), (0, 12, 13), (0, 14, 15)])}
    s = Script(orders={0: [("X", 100)]})
    res = Engine(data, FREE).run(s)
    [f] = res.fills
    assert (f.qty, f.price, f.ts) == (100, 12.0, data["X"]["ts"][1])
    assert s.seen[0] == ("X", 1, 0)
    assert s.seen[1] == ("X", 2, 100)
    assert res.equity["equity"][-1] == pytest.approx(10_000 - 1200 + 1500)


def test_slippage_and_fees_charged_in_direction_of_trade():
    data = {"X": bars([(0, 10, 10), (0, 10, 10), (0, 10, 10)])}
    cfg = Config(cash=10_000.0, costs=Costs(slippage_bps=10, commission_per_share=0.01,
                                            sec_fee_rate=0.001))
    res = Engine(data, cfg).run(Script(orders={0: [("X", 100)], 1: [("X", -100)]}))
    buy, sell = res.fills
    assert buy.price == pytest.approx(10.01) and sell.price == pytest.approx(9.99)
    assert sell.fees == pytest.approx(100 * 9.99 * 0.001) and buy.fees == 0
    assert sell.realized_pnl == pytest.approx(100 * (9.99 - 10.01))
    expected = 10_000 - 1001 - 1 + 999 - 1 - 0.999
    assert res.equity["equity"][-1] == pytest.approx(expected)


def test_buy_capped_by_cash_and_shorts_clipped_by_default():
    data = {"X": bars([(0, 100, 100), (0, 100, 100), (0, 100, 100)])}
    res = Engine(data, FREE).run(Script(orders={0: [("X", 1000)], 1: [("X", -500)]}))
    assert [f.qty for f in res.fills] == [100, -100]


def test_short_allowed_when_enabled():
    data = {"X": bars([(0, 100, 100), (0, 100, 90)])}
    cfg = Config(cash=10_000.0, costs=Costs(slippage_bps=0.0, sec_fee_rate=0.0), allow_short=True)
    res = Engine(data, cfg).run(Script(orders={0: [("X", -10)]}))
    assert res.fills[0].qty == -10
    assert res.equity["equity"][-1] == pytest.approx(10_000 + 10 * 100 - 10 * 90)


def test_split_scales_position_and_keeps_equity_continuous():
    data = {"X": bars([(0, 100, 100, 10), (0, 100, 100, 10), (1, 10, 10), (1, 10, 11)])}
    split = {"X": [Split(date(2024, 1, 3), 1, 10, "s")]}
    s = Script(orders={0: [("X", 50)]})
    res = Engine(data, FREE, splits=split).run(s)
    assert s.seen[2][2] == 500
    eq = res.equity["equity"].to_list()
    assert eq[0] == pytest.approx(10_000)
    assert eq[1] == pytest.approx(10_000 + 500 * 1)


def test_dividend_credited_on_ex_date_to_holders():
    data = {"X": bars([(0, 100, 100), (0, 100, 100), (1, 99, 99)])}
    div = {"X": [Dividend(date(2024, 1, 3), 1.0, False, "d")]}
    res = Engine(data, FREE, dividends=div).run(Script(orders={0: [("X", 10)]}))
    assert res.equity["cash"][-1] == pytest.approx(10_000 - 1000 + 10)
    assert res.equity["equity"][-1] == pytest.approx(10_000 - 1000 + 10 + 990)


def test_order_target_percent_and_multi_symbol_interleave():
    data = {
        "A": bars([(0, 10, 10), (0, 10, 10)]),
        "B": bars([(0, 20, 20), (0, 20, 20)], start=datetime(2024, 1, 2, 14, 30, 30, tzinfo=UTC)),
    }
    s = Script(orders={1: [("A", 0.5), ("B", 0.25)]}, method="order_target_percent")
    res = Engine(data, FREE).run(s)
    assert [x[0] for x in s.seen] == ["A", "B", "A", "B"]
    assert {(f.symbol, f.qty) for f in res.fills} == {("A", 500), ("B", 125)}


def test_order_target_accounts_for_pending_orders():
    data = {"X": bars([(0, 10, 10), (0, 10, 10)])}
    res = Engine(data, FREE).run(Script(orders={0: [("X", 30), ("X", 30)]},
                                        method="order_target"))
    assert [f.qty for f in res.fills] == [30]


def test_sec_fee_is_on_by_default_and_only_on_sells():
    data = {"X": bars([(0, 100, 100), (0, 100, 100), (0, 100, 100)])}
    cfg = Config(cash=10_000.0, costs=Costs(slippage_bps=0.0))
    res = Engine(data, cfg).run(Script(orders={0: [("X", 50)], 1: [("X", -50)]}))
    buy, sell = res.fills
    assert buy.fees == 0
    assert sell.fees == pytest.approx(50 * 100 * 20.60 / 1_000_000)


def test_order_for_another_symbol_waits_for_a_bar_after_the_decision():
    # A and B share timestamps; A's bar at t orders B, whose bar at t opened before the decision.
    data = {"A": bars([(0, 10, 10), (0, 10, 10)]), "B": bars([(0, 50, 100), (0, 60, 60)])}
    res = Engine(data, FREE).run(Script(orders={0: [("B", 1)]}))
    (fill,) = res.fills
    assert fill.price == 60
