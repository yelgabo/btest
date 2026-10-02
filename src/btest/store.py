import os
from datetime import datetime
from pathlib import Path

import polars as pl


def bars_dir(data_dir: Path, symbol: str) -> Path:
    return data_dir / "bars" / f"symbol={symbol}"


def year_path(data_dir: Path, symbol: str, year: int) -> Path:
    return bars_dir(data_dir, symbol) / f"year={year}" / "bars.parquet"


def write_bars(data_dir: Path, symbol: str, bars: pl.DataFrame) -> int:
    """Merge bars into the per-year files, keeping the newest copy of any duplicate ts."""
    if bars.is_empty():
        return 0
    written = 0
    for (year,), chunk in bars.group_by(pl.col("ts").dt.year(), maintain_order=True):
        path = year_path(data_dir, symbol, year)
        if path.exists():
            chunk = pl.concat([pl.read_parquet(path), chunk], how="vertical_relaxed")
        merged = chunk.unique(subset="ts", keep="last").sort("ts")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        merged.write_parquet(tmp)
        os.replace(tmp, path)
        written += merged.height
    return written


def last_ts(data_dir: Path, symbol: str) -> datetime | None:
    years = sorted(bars_dir(data_dir, symbol).glob("year=*/bars.parquet"),
                   key=lambda p: int(p.parent.name.removeprefix("year=")))
    if not years:
        return None
    return pl.read_parquet(years[-1], columns=["ts"])["ts"].max()
