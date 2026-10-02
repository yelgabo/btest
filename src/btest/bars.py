"""Candles for charts: regular-session minute bars, split- and dividend-adjusted like the
backtests see them, grouped into larger timeframes on New York session time."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from btest import loader
from btest.calendar import EXCHANGE_TZ
from btest.sources.base import Dividend, Split

TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1D": None}
MAX_CANDLES = 60_000
SESSION_OPEN_MIN = 9 * 60 + 30


def estimate(start: date, end: date, tf: str) -> int:
    days = (end - start).days * 252 / 365
    per_day = 1 if TIMEFRAMES[tf] is None else -(-390 // TIMEFRAMES[tf])
    return int(days * per_day)


def check(symbol: str, start: str, end: str, tf: str, symbols: list[str]) -> tuple[date, date]:
    if symbol not in symbols:
        raise ValueError(f"Symbol must be one of {', '.join(symbols)}.")
    if tf not in TIMEFRAMES:
        raise ValueError(f"Timeframe must be one of {', '.join(TIMEFRAMES)}.")
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise ValueError("Dates must look like 2024-01-31.") from None
    if s > e:
        raise ValueError("The start date must not be after the end date.")
    n = estimate(s, e, tf)
    if n > MAX_CANDLES:
        raise ValueError(f"That is about {n:,} candles. Pick a larger timeframe or a shorter "
                         f"range (limit {MAX_CANDLES:,}).")
    return s, e


def aggregate(bars: pl.DataFrame, tf: str) -> pl.DataFrame:
    """Minute bars from loader.load_bars (adjusted, with raw_* columns) grouped into tf bars on
    New York session time. Each bar is stamped with its first minute; backtests and charts both
    use this, so they agree on what a 15m or daily bar is."""
    if tf not in TIMEFRAMES:
        raise ValueError(f"Timeframe must be one of {', '.join(TIMEFRAMES)}.")
    n = TIMEFRAMES[tf]
    if n == 1 or bars.is_empty():
        return bars
    if n is None:
        keyed = bars.with_columns(pl.lit(0).alias("_b"))
    else:
        local = pl.col("ts").dt.convert_time_zone(EXCHANGE_TZ)
        minute = local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)
        keyed = bars.with_columns(((minute - SESSION_OPEN_MIN) // n).alias("_b"))
    aggs = [
        pl.col("ts").first(), pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
        pl.col("close").last(), pl.col("volume").sum(),
    ]
    optional = {
        "raw_open": pl.col("raw_open").first(), "raw_high": pl.col("raw_high").max(),
        "raw_low": pl.col("raw_low").min(), "raw_close": pl.col("raw_close").last(),
        "trades": pl.col("trades").sum(),
        "vwap": (pl.col("vwap") * pl.col("volume")).sum() / pl.col("volume").sum(),
        "regular": pl.col("regular").all(),
    }
    aggs += [expr.alias(name) for name, expr in optional.items() if name in bars.columns]
    return (keyed.sort("ts").group_by("date", "_b", maintain_order=True).agg(aggs)
            .drop("_b").sort("ts"))


def candles(data_dir: Path, symbol: str, start: date, end: date, tf: str,
            splits: list[Split], dividends: list[Dividend]) -> dict:
    t0 = datetime.combine(start, datetime.min.time(), UTC)
    t1 = datetime.combine(end, datetime.min.time(), UTC) + timedelta(days=1)
    bars = loader.load_bars(data_dir, symbol, t0, t1, splits, dividends)
    if bars.is_empty():
        return {"t": [], "o": [], "h": [], "l": [], "c": [], "v": [], "f": []}
    out = aggregate(bars, tf)
    return {
        "t": (out["ts"].dt.epoch("s")).to_list(),
        "o": out["open"].round(4).to_list(),
        "h": out["high"].round(4).to_list(),
        "l": out["low"].round(4).to_list(),
        "c": out["close"].round(4).to_list(),
        "v": out["volume"].round(0).cast(pl.Int64).to_list(),
        # Adjusted / raw, so the page can place fills (raw prices) on adjusted candles.
        "f": (out["close"] / out["raw_close"]).round(8).to_list(),
    }
