import pytest

from btest import bars
from btest.config import ROOT
from btest.parity import compare
from btest.runner import load_strategy_class
from tests.test_parity import CFG, synthetic

S = ROOT / "strategies"
CASES = [
    ("risk/vol_target.py", {"lookback": 10, "rebalance_band": 0.02, "target_vol": 0.03}, 300, 4),
    ("mean_reversion/rsi2.py", {"trend_ma": 20, "exit_ma": 3, "entry": 30.0}, 300, 4),
    ("trend/momentum_12m.py", {"lookback": 40, "rebalance_days": 5}, 300, 4),
    ("intraday/opening_range.py", {"range_minutes": 30}, 30, 390),
]


@pytest.mark.parametrize("path,params,days,per_day", CASES, ids=[c[0] for c in CASES])
def test_fast_path_matches_event_engine(path, params, days, per_day):
    cls = load_strategy_class(S / path)
    minute, splits, divs = synthetic(days=days, per_day=per_day)
    r = compare(cls, {"symbol": "X", **params}, "X", minute, splits, divs, CFG)
    assert r.event_fills >= 2, r
    assert r.ok, r


def test_opening_range_is_flat_by_exit_time_and_trades_once_a_day():
    from btest.engine import Config, Engine
    cls = load_strategy_class(S / "intraday" / "opening_range.py")
    minute, splits, divs = synthetic(days=30, per_day=390)
    five = bars.aggregate(minute, "5m")
    res = Engine({"X": five}, CFG, {"X": splits}, {"X": divs}).run(cls(symbol="X"))
    by_day = {}
    for f in res.fills:
        by_day.setdefault(f.ts.date(), []).append(f.qty)
    for qtys in by_day.values():
        assert sum(1 for q in qtys if q > 0) <= 1
        assert sum(qtys) == 0


def test_opening_range_half_day_carry_matches():
    """A position left open by a half day (13:00 close) is sold at the next open, and that
    first bar still counts toward the new day's opening range."""
    from datetime import UTC, datetime, timedelta

    import polars as pl

    rows = []
    # Day 1 closes at 13:00 after a rally, so the strategy is still long at the bell.
    price = 100.0
    day1 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    for m in range(210):
        o = price
        price *= 1.001 if 30 <= m < 120 else 1.0
        rows.append((day1 + timedelta(minutes=m), o, price))
    # Day 2: the first bar sets the opening-range high (101). Without it the range high would be
    # 100 and the breakout would fire about 30 minutes earlier.
    day2 = datetime(2024, 1, 3, 14, 30, tzinfo=UTC)
    rows.append((day2, 100.0, 101.0))
    for m in range(1, 390):
        target = 100.0 if m < 30 else min(103.0, 100.0 + (m - 30) * 0.05)
        rows.append((day2 + timedelta(minutes=m), rows[-1][2], target))
    rows = [(ts, ts.date(), o, c) for ts, o, c in rows]
    df = pl.DataFrame(rows, schema={"ts": pl.Datetime("us", "UTC"), "date": pl.Date,
                                    "raw_open": pl.Float64, "raw_close": pl.Float64}, orient="row")
    df = df.with_columns(pl.col("raw_open").alias("open"), pl.col("raw_close").alias("close"),
                         pl.max_horizontal("raw_open", "raw_close").alias("high"),
                         pl.min_horizontal("raw_open", "raw_close").alias("low"),
                         pl.lit(100.0).alias("volume"))
    cls = load_strategy_class(S / "intraday" / "opening_range.py")
    r = compare(cls, {"symbol": "X", "stop_at_range_low": False}, "X", df, [], [], CFG)
    assert r.event_fills >= 2 and r.ok, r
