from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from btest.sources.base import Dividend, Split

PRICE_COLS = ["open", "high", "low", "close", "vwap"]


@dataclass(frozen=True)
class Factor:
    ex_date: date
    price: float
    volume: float


def factors(splits: list[Split], dividends: list[Dividend],
            prior_close: Callable[[date], float | None]) -> list[Factor]:
    """Backward adjustment factors: each applies to every bar dated before its ex_date."""
    out = [Factor(s.ex_date, s.old_rate / s.new_rate, s.new_rate / s.old_rate) for s in splits]
    for d in dividends:
        close = prior_close(d.ex_date)
        if close is None:
            continue
        if d.rate >= close:
            raise ValueError(f"dividend {d.rate} on {d.ex_date} >= prior close {close}")
        out.append(Factor(d.ex_date, 1 - d.rate / close, 1.0))
    return sorted(out, key=lambda f: f.ex_date)


def apply(bars: pl.DataFrame, fs: list[Factor], date_col: str = "date") -> pl.DataFrame:
    """Multiply prices by the product of every factor whose ex_date is after the bar's date."""
    if not fs:
        return bars.with_columns(pl.col("volume").cast(pl.Float64))
    by_date: dict[date, list[float]] = {}
    for f in fs:
        p, v = by_date.get(f.ex_date, [1.0, 1.0])
        by_date[f.ex_date] = [p * f.price, v * f.volume]
    steps = []
    cum_p = cum_v = 1.0
    for ex in sorted(by_date, reverse=True):
        cum_p *= by_date[ex][0]
        cum_v *= by_date[ex][1]
        # Covers bar dates up to and including the day before ex_date.
        steps.append((ex - timedelta(days=1), cum_p, cum_v))
    table = pl.DataFrame(steps, schema={"_key": pl.Date, "_pf": pl.Float64, "_vf": pl.Float64},
                         orient="row").sort("_key")
    out = bars.sort("ts").join_asof(table, left_on=date_col, right_on="_key",
                                    strategy="forward")
    out = out.with_columns(pl.col("_pf").fill_null(1.0), pl.col("_vf").fill_null(1.0))
    return out.with_columns(
        *[(pl.col(c) * pl.col("_pf")).alias(c) for c in PRICE_COLS if c in out.columns],
        (pl.col("volume") * pl.col("_vf")).alias("volume"),
    ).drop("_key", "_pf", "_vf")
