from datetime import date
from pathlib import Path

import polars as pl
import psycopg

from btest import db, loader
from btest.ingest import log
from btest.sources.alpaca import AlpacaSource


def sample_days(sessions: pl.DataFrame, event_dates: list[date],
                have_from: date, have_to: date) -> list[date]:
    """First session of each year, plus the sessions either side of every corporate action."""
    days = sessions.filter(pl.col("date").is_between(have_from, have_to))["date"].to_list()
    picked = set()
    seen_years = set()
    for d in days:
        if d.year not in seen_years:
            seen_years.add(d.year)
            picked.add(d)
    for ex in event_dates:
        before = [d for d in days if d < ex]
        after = [d for d in days if d >= ex]
        if before:
            picked.add(before[-1])
        if after:
            picked.add(after[0])
    return sorted(picked)


def check_adjustments(conn: psycopg.Connection, source: AlpacaSource, data_dir: Path,
                      symbols: list[str]) -> pl.DataFrame:
    results = []
    for symbol in symbols:
        splits = db.get_splits(conn, symbol)
        dividends = db.get_dividends(conn, symbol)
        closes = loader.daily_closes(data_dir, symbol)
        have_from, have_to = closes["date"].min(), closes["date"].max()
        sessions = db.get_sessions(conn, have_from, have_to)
        events = [s.ex_date for s in splits] + [d.ex_date for d in dividends]
        days = sample_days(sessions, events, have_from, have_to)
        for i, day in enumerate(days, 1):
            row = sessions.filter(pl.col("date") == day).row(0, named=True)
            start, end = row["open_utc"], row["close_utc"]
            ours = loader.load_bars(data_dir, symbol, start, end, splits, dividends)
            theirs = source.bars(symbol, start, end, adjustment="all")
            joined = ours.select("ts", "close").join(
                theirs.select("ts", pl.col("close").alias("ref")), on="ts", how="inner",
            )
            rel = ((joined["close"] - joined["ref"]).abs() / joined["ref"])
            results.append({
                "symbol": symbol,
                "date": day,
                "ours": ours.height,
                "theirs": theirs.height,
                "matched": joined.height,
                "max_rel_err": rel.max() if joined.height else None,
            })
            if i % 10 == 0 or i == len(days):
                log(f"check {symbol}: {i}/{len(days)} days ({100 * i / len(days):.0f}%)")
    return pl.DataFrame(results)
