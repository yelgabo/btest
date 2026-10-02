from datetime import UTC, datetime

import polars as pl

from btest import store
from btest.sources.base import BAR_SCHEMA


def frame(rows):
    return pl.DataFrame(
        [(ts, c, c, c, c, 1, 1, c) for ts, c in rows], schema=BAR_SCHEMA, orient="row",
    )


def test_write_merges_overlap_partitions_by_year_and_tracks_last_ts(tmp_path):
    a = datetime(2023, 12, 29, 20, 59, tzinfo=UTC)
    b = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    c = datetime(2024, 1, 2, 14, 31, tzinfo=UTC)
    store.write_bars(tmp_path, "SPY", frame([(a, 1.0), (b, 2.0)]))
    store.write_bars(tmp_path, "SPY", frame([(b, 2.5), (c, 3.0)]))
    y2024 = pl.read_parquet(store.year_path(tmp_path, "SPY", 2024))
    assert y2024["close"].to_list() == [2.5, 3.0]
    assert store.year_path(tmp_path, "SPY", 2023).exists()
    assert store.last_ts(tmp_path, "SPY") == c


def test_last_ts_is_none_without_data(tmp_path):
    assert store.last_ts(tmp_path, "SPY") is None
