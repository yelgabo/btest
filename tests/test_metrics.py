from datetime import date, timedelta

import polars as pl
import pytest

from btest import metrics


def series(values, start=date(2024, 1, 1)):
    return pl.DataFrame({"date": [start + timedelta(days=i) for i in range(len(values))],
                         "equity": values})


def test_drawdown_depth_and_duration():
    m = metrics.compute(series([100, 120, 90, 100, 130, 117]))
    assert m["max_drawdown"] == pytest.approx(90 / 120 - 1)
    assert m["max_drawdown_days"] == 2
    assert m["total_return"] == pytest.approx(0.17)


def test_cagr_over_two_years():
    eq = pl.DataFrame({"date": [date(2020, 1, 1), date(2022, 1, 1)], "equity": [100.0, 121.0]})
    assert metrics.compute(eq)["cagr"] == pytest.approx(0.1, abs=1e-3)


def test_sharpe_subtracts_risk_free():
    eq = series([100 * 1.001 ** i * (1.002 if i % 2 else 1) for i in range(50)])
    rf = pl.DataFrame({"date": [date(2023, 1, 1)], "rate": [5.0]})
    assert metrics.compute(eq, rf)["sharpe"] < metrics.compute(eq)["sharpe"]
