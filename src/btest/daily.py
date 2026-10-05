"""Daily rows for portfolio strategies, built from minute bars with the live timing.

A decision on day d happens `decide_min` minutes before the session close and sees, for d
itself, only bars that started at or before the cutoff (`data_min` minutes before close). That
is what the live system has at 15:30: the free SIP feed is 15 minutes delayed, so the last
complete minute is the one starting 15:14. Orders fill at the open of the first bar starting
`fill_min` minutes before close or later. Early-close days shift all three with the close.
"""

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import polars as pl

from btest import adjust, loader, store
from btest.calendar import exchange_date
from btest.sources.base import Dividend, Split

CACHE_VERSION = 1


@dataclass(frozen=True)
class Timing:
    decide_min: int = 30
    data_min: int = 46
    fill_min: int = 15

    def to_dict(self) -> dict:
        return asdict(self)


def decision_times(sessions: pl.DataFrame, timing: Timing) -> pl.DataFrame:
    """Per session: decision time, last bar start the decision may see, first fill bar start."""
    return sessions.select(
        "date",
        (pl.col("close_utc") - pl.duration(minutes=timing.decide_min)).alias("decide_ts"),
        (pl.col("close_utc") - pl.duration(minutes=timing.data_min)).alias("cutoff_ts"),
        (pl.col("close_utc") - pl.duration(minutes=timing.fill_min)).alias("fill_ts"),
    )


def raw_daily(data_dir: Path, symbol: str, sessions: pl.DataFrame,
              timing: Timing) -> pl.DataFrame:
    """Unadjusted per-day values. Full-day OHLCV, the same fields cut at the decision cutoff,
    the fill price, and the last trade of the day for marking positions."""
    raw = loader.read_raw(data_dir, symbol, columns="ts, open, high, low, close, volume, regular")
    if raw.is_empty():
        return pl.DataFrame()
    times = decision_times(sessions, timing)
    bars = (raw.filter(pl.col("regular"))
            .with_columns(exchange_date(pl.col("ts")).alias("date"),
                          pl.col("volume").cast(pl.Float64))
            .join(times, on="date", how="inner")
            .sort("ts"))
    seen = pl.col("ts") <= pl.col("cutoff_ts")
    late = pl.col("ts") >= pl.col("fill_ts")
    return bars.group_by("date").agg(
        pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
        pl.col("close").last(), pl.col("volume").sum(),
        pl.col("open").filter(seen).first().alias("cut_open"),
        pl.col("high").filter(seen).max().alias("cut_high"),
        pl.col("low").filter(seen).min().alias("cut_low"),
        pl.col("close").filter(seen).last().alias("cut_close"),
        pl.col("volume").filter(seen).sum().alias("cut_volume"),
        pl.col("open").filter(late).first().alias("fill"),
    ).sort("date")


def _cache_path(data_dir: Path, symbol: str, timing: Timing) -> Path:
    t = timing
    return (data_dir / "daily" / f"v{CACHE_VERSION}-{t.decide_min}-{t.data_min}-{t.fill_min}"
            / f"{symbol}.parquet")


def cached_raw_daily(data_dir: Path, symbol: str, sessions: pl.DataFrame,
                     timing: Timing) -> pl.DataFrame:
    """raw_daily, cached beside the minute files and rebuilt when any of them is newer."""
    path = _cache_path(data_dir, symbol, timing)
    sources = list((data_dir / "bars" / f"symbol={symbol}").glob("year=*/bars.parquet"))
    if not sources:
        return pl.DataFrame()
    newest = max(p.stat().st_mtime for p in sources)
    if path.exists() and path.stat().st_mtime >= newest:
        cached = pl.read_parquet(path)
        # A cache built from a shorter session list stops early; rebuild it.
        last_bar = store.last_ts(data_dir, symbol)
        covered = sessions.filter(pl.col("open_utc") <= last_bar)["date"].max()
        if not cached.is_empty() and covered is not None and cached["date"].max() >= covered:
            return cached
    df = raw_daily(data_dir, symbol, sessions, timing)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.write_parquet(tmp)
    tmp.replace(path)
    return df


PRICE_FIELDS = ["open", "high", "low", "close", "cut_open", "cut_high", "cut_low", "cut_close"]


def adjusted_daily(raw: pl.DataFrame, splits: list[Split],
                   dividends: list[Dividend]) -> pl.DataFrame:
    """Adds adjusted price columns (same names) and keeps the traded prices as raw_*."""
    if raw.is_empty():
        return raw
    fs = adjust.factors(splits, dividends, loader.prior_close_lookup(raw.select("date", "close")))
    unit = adjust.apply(raw.select("date", pl.lit(1.0).alias("close"), pl.lit(1.0).alias("volume"),
                                   pl.col("date").cast(pl.Datetime("us", "UTC")).alias("ts")),
                        fs)
    return raw.sort("date").with_columns(
        *[pl.col(c).alias(f"raw_{c}") for c in PRICE_FIELDS],
        *[(pl.col(c) * unit["close"]).alias(c) for c in PRICE_FIELDS],
        *[(pl.col(c) * unit["volume"]).alias(c) for c in ("volume", "cut_volume")],
    )


def load(data_dir: Path, symbol: str, sessions: pl.DataFrame, timing: Timing,
         splits: list[Split], dividends: list[Dividend], end: date | None = None) -> pl.DataFrame:
    df = adjusted_daily(cached_raw_daily(data_dir, symbol, sessions, timing), splits, dividends)
    if end is not None and not df.is_empty():
        df = df.filter(pl.col("date") <= end)
    return df
