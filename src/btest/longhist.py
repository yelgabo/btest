"""The long-history data source: Yahoo's daily adjusted closes for btest's symbols from 1995 or
each symbol's first trading day, whichever is later (docs/superpowers/specs/
2026-10-06-long-history-data.md). Day bars, so it is kept apart from the minute-bar store.
A strategy decides on a session's close and its orders fill at the next session's open; with
decide_at="open" it decides on a session's open and fills at that session's close."""
import json
import time
import urllib.request
from datetime import UTC, date, datetime

import polars as pl
import psycopg

from btest.calendar import nyse_sessions

START = date(1995, 1, 3)
# Yahoo carries an older product's prices under these tickers; the fund starts on this day.
# SMH: the Semiconductor HOLDRS trust until VanEck's ETF began trading on 2011-12-21.
FIRST_DAY = {"SMH": date(2011, 12, 21)}
PRICE_COLS = ("open", "high", "low", "close", "raw_close", "fill", "cut_open", "cut_high",
              "cut_low", "cut_close", "raw_cut_close")


def yahoo(symbol: str) -> pl.DataFrame:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?period1=0&period2=4000000000&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.load(urllib.request.urlopen(req, timeout=60))["chart"]["result"][0]
    time.sleep(0.5)
    days = [datetime.fromtimestamp(t + r["meta"]["gmtoffset"], UTC).date() for t in r["timestamp"]]
    q = r["indicators"]["quote"][0]
    raw = pl.DataFrame({"date": days, "open": q["open"], "raw": q["close"],
                        "close": r["indicators"]["adjclose"][0]["adjclose"]},
                       schema={"date": pl.Date, "open": pl.Float64, "raw": pl.Float64,
                               "close": pl.Float64}).drop_nulls()
    # Yahoo adjusts only the close for dividends; scale the open by the same day's factor.
    return raw.select("date", (pl.col("open") * pl.col("close") / pl.col("raw")).alias("open"),
                      "close")


def build(symbols: list[str], end: date) -> pl.DataFrame:
    """Long table of symbol, date, open, close on NYSE sessions from START or the symbol's first
    day, before end. A session Yahoo skipped repeats the previous close as open and close."""
    # Before end, because Yahoo's row for today holds a live price until the close.
    days = nyse_sessions(START, end).select("date").filter(pl.col("date") < end)
    parts = []
    for symbol in symbols:
        px = yahoo(symbol)
        if symbol in FIRST_DAY:
            px = px.filter(pl.col("date") >= FIRST_DAY[symbol])
        rows = days.filter(pl.col("date") >= px["date"].min()).join(px, on="date", how="left")
        rows = rows.with_columns(pl.col("close").forward_fill())
        parts.append(rows.with_columns(pl.col("open").fill_null(pl.col("close")),
                                       pl.lit(symbol).alias("symbol")))
    return pl.concat(parts).select("symbol", "date", "open", "close")


def store(conn: psycopg.Connection, rows: pl.DataFrame, replace_all: bool = True) -> None:
    """Replaces the whole table, or with replace_all=False only the symbols in rows."""
    if replace_all:
        conn.execute("DELETE FROM market.longhist")
    else:
        conn.execute("DELETE FROM market.longhist WHERE symbol = ANY(%s)",
                     (rows["symbol"].unique().to_list(),))
    with conn.cursor() as cur:
        with cur.copy("COPY market.longhist (symbol, date, open, close) FROM STDIN") as cp:
            for row in rows.iter_rows():
                cp.write_row(row)
    conn.commit()


def frames(conn: psycopg.Connection, symbols: list[str], end: date,
           decide_at: str = "close") -> dict[str, pl.DataFrame]:
    """Per-symbol daily frames in the shape btest.daily.load returns. With decide_at="close" the
    strategy sees each session's close; fill is the next session's open, so an order placed on
    what the close showed trades after it. On the last row there is no next open, so the engine
    drops that decision. With decide_at="open" the strategy sees today's open (and earlier
    sessions in full) and fills at today's close."""
    rows = conn.execute("SELECT symbol, date, open, close FROM market.longhist "
                        "WHERE symbol = ANY(%s) AND date < %s ORDER BY symbol, date",
                        (symbols, end)).fetchall()
    t = pl.DataFrame(rows, schema={"symbol": pl.Utf8, "date": pl.Date, "open": pl.Float64,
                                   "close": pl.Float64}, orient="row")
    out = {}
    for s in symbols:
        d = t.filter(pl.col("symbol") == s)
        if d.is_empty():
            raise SystemExit(f"no long-history data for {s}; run `btest longhist`")
        if decide_at == "open":
            known = [pl.col("open").alias(c) for c in
                     ("cut_open", "cut_high", "cut_low", "cut_close", "raw_cut_close")]
            out[s] = d.select("date", "open", *[pl.col("close").alias(c) for c in
                                                ("high", "low", "close", "raw_close", "fill")],
                              *known, pl.lit(1e9).alias("volume"), pl.lit(1e9).alias("cut_volume"))
        else:
            out[s] = d.select("date", *[pl.col("close").alias(c) for c in PRICE_COLS if c != "fill"],
                              pl.col("open").shift(-1).alias("fill"),
                              pl.lit(1e9).alias("volume"), pl.lit(1e9).alias("cut_volume"))
    return out
