
import polars as pl
import pytest

from btest import bars
from btest.config import ROOT
from btest.engine import Config, Costs, Engine
from btest.parity import compare
from btest.runner import load_strategy_class, strategy_timeframe
from btest.strategy import Strategy
from tests.test_parity import CFG, synthetic

TREND = load_strategy_class(ROOT / "strategies" / "trend" / "sma_200.py")


def test_aggregate_keeps_raw_prices_and_session_buckets():
    minute, _, _ = synthetic(days=3, per_day=60)
    daily = bars.aggregate(minute, "1D")
    assert daily.height == 3
    first = minute.filter(pl.col("date") == minute["date"][0])
    row = daily.row(0, named=True)
    assert row["open"] == first["open"][0] and row["close"] == first["close"][-1]
    assert row["raw_open"] == first["raw_open"][0] and row["raw_close"] == first["raw_close"][-1]
    assert row["high"] == first["high"].max() and row["volume"] == first["volume"].sum()
    assert row["ts"] == first["ts"][0]
    assert bars.aggregate(minute, "1m") is minute


def test_daily_strategy_fills_at_next_day_open():
    minute, splits, divs = synthetic()
    daily = bars.aggregate(minute, "1D")
    res = Engine({"X": daily}, Config(cash=50_000.0, costs=Costs(slippage_bps=0.0)),
                 {"X": splits}, {"X": divs}).run(TREND(symbol="X", length=5))
    assert res.fills
    opens = dict(zip(daily["ts"].to_list(), daily["raw_open"].to_list()))
    for f in res.fills:
        assert f.ts in opens and f.price == pytest.approx(opens[f.ts])


def test_daily_fast_path_matches_event_engine():
    minute, splits, divs = synthetic()
    for length, buffer in [(5, 0.0), (8, 0.01)]:
        r = compare(TREND, {"symbol": "X", "length": length, "buffer": buffer}, "X",
                    minute, splits, divs, CFG)
        assert r.event_fills >= 2 and r.ok, r


def test_unknown_timeframe_is_refused():
    class Bad(Strategy):
        timeframe = "2h"
    with pytest.raises(SystemExit, match="2h"):
        strategy_timeframe(Bad)
