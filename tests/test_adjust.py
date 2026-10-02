from datetime import UTC, date, datetime

import polars as pl
import pytest

from btest import adjust
from btest.sources.base import Dividend, Split


def bars(rows):
    return pl.DataFrame(
        [(datetime(d.year, d.month, d.day, 15, tzinfo=UTC), d, c, v) for d, c, v in rows],
        schema={"ts": pl.Datetime("us", "UTC"), "date": pl.Date, "close": pl.Float64,
                "volume": pl.Int64},
        orient="row",
    )


def test_split_scales_prices_and_volume_before_ex_date_only():
    df = bars([(date(2024, 6, 7), 1200.0, 100), (date(2024, 6, 10), 121.0, 1000)])
    fs = adjust.factors([Split(date(2024, 6, 10), 1, 10, "s")], [], lambda _: None)
    out = adjust.apply(df, fs)
    assert out["close"].to_list() == pytest.approx([120.0, 121.0])
    assert out["volume"].to_list() == pytest.approx([1000.0, 1000.0])


def test_dividend_factor_uses_prior_close():
    df = bars([(date(2024, 3, 14), 100.0, 10), (date(2024, 3, 15), 99.0, 10)])
    fs = adjust.factors([], [Dividend(date(2024, 3, 15), 2.0, False, "d")],
                        lambda ex: 100.0 if ex == date(2024, 3, 15) else None)
    out = adjust.apply(df, fs)
    assert out["close"].to_list() == pytest.approx([98.0, 99.0])
    assert out["volume"].to_list() == pytest.approx([10.0, 10.0])


def test_factors_compound_across_events_and_same_day_events():
    df = bars([
        (date(2021, 7, 19), 800.0, 1),
        (date(2021, 7, 20), 200.0, 1),
        (date(2024, 6, 7), 1200.0, 1),
        (date(2024, 6, 10), 120.0, 1),
    ])
    fs = adjust.factors(
        [Split(date(2021, 7, 20), 1, 4, "a"), Split(date(2024, 6, 10), 1, 10, "b")],
        [Dividend(date(2024, 6, 10), 12.0, False, "c")],
        lambda _: 1200.0,
    )
    out = adjust.apply(df, fs)
    assert out["close"].to_list() == pytest.approx([800 / 40 * 0.99, 200 / 10 * 0.99,
                                                    1200 / 10 * 0.99, 120.0])


def test_dividend_without_prior_close_is_skipped():
    fs = adjust.factors([], [Dividend(date(2016, 1, 4), 1.0, False, "d")], lambda _: None)
    assert fs == []


def test_dividend_larger_than_price_is_rejected():
    with pytest.raises(ValueError):
        adjust.factors([], [Dividend(date(2024, 1, 2), 5.0, False, "d")], lambda _: 4.0)
