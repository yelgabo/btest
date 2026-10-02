from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import polars as pl

BAR_SCHEMA = {
    "ts": pl.Datetime("us", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "trades": pl.Int64,
    "vwap": pl.Float64,
}


@dataclass(frozen=True)
class Split:
    ex_date: date
    old_rate: float
    new_rate: float
    source_id: str


@dataclass(frozen=True)
class Dividend:
    ex_date: date
    rate: float
    special: bool
    source_id: str


class DataSource(Protocol):
    name: str

    def bars(self, symbol: str, start: datetime, end: datetime) -> pl.DataFrame: ...

    def splits(self, symbol: str, start: date, end: date) -> list[Split]: ...

    def dividends(self, symbol: str, start: date, end: date) -> list[Dividend]: ...
