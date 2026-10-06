"""The long-history data source: daily total-return closes from 1995 under ETF names, each ETF
from its launch and a stand-in fund or index before (docs/superpowers/specs/
2026-10-06-long-history-data.md). The slots match docs/research/olps-replication/
long_history.py, which keeps its own cached copy as the record of the 1995-2015 test."""
import io
import json
import time
import urllib.request
import zipfile
from datetime import UTC, date, datetime

import numpy as np
import polars as pl
import psycopg

from btest.calendar import nyse_sessions

START = date(1995, 1, 3)
DIA_YIELD = 0.02
# Symbol: stand-in before the ETF's first day. A list is a fixed-weight mix rebalanced daily;
# "ff:" is a Ken French industry; "^DJI+yield" is the Dow price index plus DIA_YIELD a year,
# because no Dow fund with dividends goes back to 1995.
STAND_INS = {
    "SPY": None,
    "QQQ": "RYOCX",
    "IWM": "NAESX",
    "DIA": "^DJI+yield",
    "EFA": [("VEURX", 0.6), ("VPACX", 0.4)],
    "EEM": "VEIEX",
    "XLK": "FSPTX",
    "XLF": "FIDSX",
    "XLV": "FSPHX",
    "XLE": "FSENX",
    # Fidelity Select Industrials' ticker now belongs to a fund that starts in 2025.
    "XLI": "ff:Manuf",
    "XLY": "FSCPX",
    "XLP": "FDFAX",
    "XLU": "FSUTX",
    "XLB": "FSDPX",
    "XLRE": "FRESX",
    "AGG": "VBMFX",
}
SYMBOLS = list(STAND_INS)
UA = {"User-Agent": "Mozilla/5.0"}
FRENCH = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
          "12_Industry_Portfolios_daily_CSV.zip")


def yahoo(symbol: str) -> pl.DataFrame:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?period1=0&period2=4000000000&interval=1d&events=div,split")
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                         timeout=60))["chart"]["result"][0]
    time.sleep(0.5)
    days = [datetime.fromtimestamp(t + r["meta"]["gmtoffset"], UTC).date() for t in r["timestamp"]]
    return pl.DataFrame({"date": days, "price": r["indicators"]["adjclose"][0]["adjclose"]},
                        schema={"date": pl.Date, "price": pl.Float64}).drop_nulls()


def french(industry: str) -> pl.DataFrame:
    raw = urllib.request.urlopen(urllib.request.Request(FRENCH, headers=UA), timeout=60).read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    lines = zf.read(zf.namelist()[0]).decode().splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith(",NoDur"))
    # The first block is value-weighted; it ends at the first blank line.
    end = next(i for i in range(head + 1, len(lines)) if not lines[i].strip())
    t = pl.read_csv(io.StringIO("\n".join(lines[head:end])), infer_schema=False)
    return t.select(
        pl.col(t.columns[0]).str.strptime(pl.Date, "%Y%m%d").alias("date"),
        (1 + pl.col(industry).str.strip_chars().cast(pl.Float64) / 100).cum_prod()
        .alias("price"))


def returns(px: pl.DataFrame) -> pl.DataFrame:
    return px.sort("date").select(
        "date", (pl.col("price") / pl.col("price").shift(1) - 1).alias("ret")).drop_nulls()


def stand_in_returns(spec) -> pl.DataFrame:
    if isinstance(spec, list):
        j = None
        for s, _ in spec:
            r = returns(yahoo(s)).rename({"ret": s})
            j = r if j is None else j.join(r, on="date")
        return j.select("date", sum(pl.col(s) * w for s, w in spec).alias("ret"))
    if spec.startswith("ff:"):
        return returns(french(spec[3:]))
    if spec == "^DJI+yield":
        return returns(yahoo("^DJI")).with_columns(pl.col("ret") + DIA_YIELD / 252)
    return returns(yahoo(spec))


def build(end: date) -> pl.DataFrame:
    """Long table of symbol, date, close (100 on START) and source, on NYSE sessions before
    end. A session a source skipped counts as a zero return."""
    # Before end, because Yahoo's row for today holds a live price until the close.
    days = nyse_sessions(START, end).select("date").filter(pl.col("date") < end)
    parts = []
    for symbol, spec in STAND_INS.items():
        etf = yahoo(symbol)
        launch = etf["date"].min()
        r = returns(etf).with_columns(pl.lit(symbol).alias("source"))
        if spec is not None:
            label = spec if isinstance(spec, str) else "+".join(
                f"{w:.0%} {s}" for s, w in spec)
            r = pl.concat([
                stand_in_returns(spec).filter(pl.col("date") <= launch)
                .with_columns(pl.lit(label).alias("source")),
                r.filter(pl.col("date") > launch)])
        col = days.join(r, on="date", how="left").with_columns(
            pl.col("ret").fill_null(0.0), pl.col("source").forward_fill().backward_fill())
        ret = col["ret"].to_numpy().copy()
        ret[0] = 0.0
        parts.append(col.select("date", "source").with_columns(
            pl.lit(symbol).alias("symbol"), pl.Series("close", 100 * np.cumprod(1 + ret))))
    return pl.concat(parts).select("symbol", "date", "close", "source")


def store(conn: psycopg.Connection, rows: pl.DataFrame) -> None:
    conn.execute("DELETE FROM market.longhist")
    with conn.cursor() as cur:
        with cur.copy("COPY market.longhist (symbol, date, close, source) FROM STDIN") as cp:
            for row in rows.iter_rows():
                cp.write_row(row)
    conn.commit()


def frames(conn: psycopg.Connection, symbols: list[str], end: date) -> dict[str, pl.DataFrame]:
    """Per-symbol daily frames in the shape btest.daily.load returns, every price the close."""
    missing = [s for s in symbols if s not in STAND_INS]
    if missing:
        raise SystemExit(f"Long-history data has {', '.join(SYMBOLS)}; not "
                         f"{', '.join(missing)}.")
    rows = conn.execute("SELECT symbol, date, close FROM market.longhist "
                        "WHERE symbol = ANY(%s) AND date < %s ORDER BY symbol, date",
                        (symbols, end)).fetchall()
    t = pl.DataFrame(rows, schema={"symbol": pl.Utf8, "date": pl.Date, "close": pl.Float64},
                     orient="row")
    out = {}
    for s in symbols:
        d = t.filter(pl.col("symbol") == s)
        if d.is_empty():
            raise SystemExit(f"no long-history data for {s}; run `btest longhist`")
        close = pl.col("close")
        out[s] = d.select(
            "date", *[close.alias(c) for c in (
                "open", "high", "low", "close", "raw_close", "fill", "cut_open", "cut_high",
                "cut_low", "cut_close", "raw_cut_close")],
            pl.lit(1e9).alias("volume"), pl.lit(1e9).alias("cut_volume"))
    return out
