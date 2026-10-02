from datetime import UTC, date, datetime

import polars as pl
import pytest

from btest import loader, store
from btest.sources.base import BAR_SCHEMA, Dividend


def test_load_bars_filters_regular_and_adjusts_with_stored_prior_close(tmp_path):
    rows = [
        (datetime(2024, 3, 14, 19, 59, tzinfo=UTC), 100.0, True),
        (datetime(2024, 3, 14, 20, 30, tzinfo=UTC), 105.0, False),
        (datetime(2024, 3, 15, 13, 30, tzinfo=UTC), 99.0, True),
    ]
    df = pl.DataFrame(
        [(ts, c, c, c, c, 10, 1, c) for ts, c, _ in rows], schema=BAR_SCHEMA, orient="row",
    ).with_columns(pl.Series("regular", [r for *_, r in rows]))
    store.write_bars(tmp_path, "SPY", df)

    out = loader.load_bars(
        tmp_path, "SPY", datetime(2024, 3, 14, tzinfo=UTC), datetime(2024, 3, 16, tzinfo=UTC),
        [], [Dividend(date(2024, 3, 15), 2.0, False, "d")],
    )
    assert out["close"].to_list() == pytest.approx([98.0, 99.0])
    assert out["raw_close"].to_list() == [100.0, 99.0]
    assert out["date"].to_list() == [date(2024, 3, 14), date(2024, 3, 15)]
    assert out["ts"].dtype == pl.Datetime("us", "UTC")
