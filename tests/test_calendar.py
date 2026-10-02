from datetime import UTC, date, datetime

import polars as pl

from btest.calendar import mark_regular, nyse_sessions


def test_half_day_close_and_extended_hours():
    sessions = nyse_sessions(date(2024, 11, 29), date(2024, 11, 29))
    ts = [
        datetime(2024, 11, 29, 14, 29, tzinfo=UTC),
        datetime(2024, 11, 29, 14, 30, tzinfo=UTC),
        datetime(2024, 11, 29, 17, 59, tzinfo=UTC),
        datetime(2024, 11, 29, 18, 0, tzinfo=UTC),
        datetime(2024, 11, 30, 15, 0, tzinfo=UTC),
    ]
    bars = pl.DataFrame({"ts": ts}, schema={"ts": pl.Datetime("us", "UTC")})
    assert mark_regular(bars, sessions)["regular"].to_list() == [False, True, True, False, False]
