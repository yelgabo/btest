from datetime import UTC, date, datetime

import polars as pl
import pytest

from btest.config import ROOT
from btest.runner import benchmark_equity, load_strategy_class


def test_example_strategy_loads_with_defaults():
    cls = load_strategy_class(ROOT / "strategies" / "ma_cross.py")
    assert cls(fast=10).params["slow"] == 390
    with pytest.raises(ValueError):
        cls(nonsense=1)


def test_benchmark_uses_last_close_per_day_and_fills_gaps():
    bars = pl.DataFrame({
        "ts": [datetime(2024, 1, 2, 15, tzinfo=UTC), datetime(2024, 1, 2, 20, 59, tzinfo=UTC),
               datetime(2024, 1, 4, 20, 59, tzinfo=UTC)],
        "date": [date(2024, 1, 2), date(2024, 1, 2), date(2024, 1, 4)],
        "close": [99.0, 100.0, 110.0],
    })
    dates = pl.Series([date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)])
    out = benchmark_equity(bars, dates, 1000.0)
    assert out["benchmark"].to_list() == pytest.approx([1000.0, 1000.0, 1100.0])
