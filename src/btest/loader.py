import bisect
from datetime import date, datetime
from pathlib import Path

import duckdb
import polars as pl

from btest import adjust
from btest.calendar import exchange_date
from btest.sources.base import Dividend, Split
from btest.store import bars_dir

RAW_COLS = ["open", "high", "low", "close"]


def read_raw(data_dir: Path, symbol: str, start: datetime | None = None,
             end: datetime | None = None, columns: str = "*") -> pl.DataFrame:
    files = bars_dir(data_dir, symbol) / "year=*" / "bars.parquet"
    where, params = [], []
    if start is not None:
        where.append("ts >= ?")
        params.append(start)
    if end is not None:
        where.append("ts < ?")
        params.append(end)
    sql = f"SELECT {columns} FROM read_parquet('{files}')"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with duckdb.connect() as con:
        con.execute("SET TimeZone = 'UTC'")
        df = con.execute(sql + " ORDER BY ts", params).pl()
    return df.with_columns(pl.col("ts").dt.convert_time_zone("UTC"))


def daily_closes(data_dir: Path, symbol: str) -> pl.DataFrame:
    raw = read_raw(data_dir, symbol, columns="ts, close, regular")
    return (
        raw.filter(pl.col("regular"))
        .group_by(exchange_date(pl.col("ts")).alias("date"))
        .agg(pl.col("close").sort_by("ts").last())
        .sort("date")
    )


def prior_close_lookup(closes: pl.DataFrame):
    dates = closes["date"].to_list()
    values = closes["close"].to_list()

    def prior_close(ex_date: date) -> float | None:
        i = bisect.bisect_left(dates, ex_date)
        return values[i - 1] if i > 0 else None

    return prior_close


def load_bars(data_dir: Path, symbol: str, start: datetime, end: datetime,
              splits: list[Split], dividends: list[Dividend],
              regular_only: bool = True) -> pl.DataFrame:
    """Adjusted bars in [start, end), with the raw OHLC kept in raw_* columns for fills.

    Adjustment uses every known corporate action, so prices before the latest split or
    dividend differ from what printed on the tape but returns are continuous.
    """
    bars = read_raw(data_dir, symbol, start, end)
    if regular_only:
        bars = bars.filter(pl.col("regular"))
    bars = bars.with_columns(
        exchange_date(pl.col("ts")).alias("date"),
        *[pl.col(c).alias(f"raw_{c}") for c in RAW_COLS],
    )
    lookup = prior_close_lookup(daily_closes(data_dir, symbol)) if dividends else None
    fs = adjust.factors(splits, dividends, lookup or (lambda _: None))
    return adjust.apply(bars, fs)
