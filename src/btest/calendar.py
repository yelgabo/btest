from datetime import date

import pandas_market_calendars as mcal
import polars as pl

EXCHANGE_TZ = "America/New_York"
SESSION_SCHEMA = {
    "date": pl.Date,
    "open_utc": pl.Datetime("us", "UTC"),
    "close_utc": pl.Datetime("us", "UTC"),
}


def nyse_sessions(start: date, end: date) -> pl.DataFrame:
    sched = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
    return pl.DataFrame({
        "date": [d.date() for d in sched.index],
        "open_utc": sched["market_open"].dt.as_unit("us").tolist(),
        "close_utc": sched["market_close"].dt.as_unit("us").tolist(),
    }, schema=SESSION_SCHEMA)


def exchange_date(ts: pl.Expr) -> pl.Expr:
    return ts.dt.convert_time_zone(EXCHANGE_TZ).dt.date()


def mark_regular(bars: pl.DataFrame, sessions: pl.DataFrame) -> pl.DataFrame:
    # A bar's timestamp is its open, so the last regular bar opens one minute before close.
    joined = bars.with_columns(exchange_date(pl.col("ts")).alias("_date")).join(
        sessions, left_on="_date", right_on="date", how="left",
    )
    return joined.with_columns(
        ((pl.col("ts") >= pl.col("open_utc")) & (pl.col("ts") < pl.col("close_utc")))
        .fill_null(False)
        .alias("regular"),
    ).drop("_date", "open_utc", "close_utc")
