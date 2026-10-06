"""Total-return series for the 16 ETF slots from 1995: each ETF from its launch, and before it a
stand-in fund or index (Yahoo adjusted closes; Ken French 12-industry daily returns for XLI;
the Dow price index plus a 2% yield for DIA). Downloads are cached under data/longhist/.

Run directly to print how closely each stand-in tracked its ETF where both exist."""
import io
import json
import time
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from btest.calendar import nyse_sessions

CACHE = Path("data/longhist")
START, END = date(1995, 1, 3), date(2026, 10, 2)
DIA_YIELD = 0.02
# Slot: (ETF, stand-in before its launch). A list is a fixed-weight mix rebalanced daily;
# "ff:" is a Ken French industry; "^DJI+yield" is the Dow price index plus DIA_YIELD a year.
SLOTS = {
    "SPY": ("SPY", None),
    "QQQ": ("QQQ", "RYOCX"),
    "IWM": ("IWM", "NAESX"),
    "DIA": ("DIA", "^DJI+yield"),
    "EFA": ("EFA", [("VEURX", 0.6), ("VPACX", 0.4)]),
    "EEM": ("EEM", "VEIEX"),
    "XLK": ("XLK", "FSPTX"),
    "XLF": ("XLF", "FIDSX"),
    "XLV": ("XLV", "FSPHX"),
    "XLE": ("XLE", "FSENX"),
    "XLI": ("XLI", "ff:Manuf"),
    "XLY": ("XLY", "FSCPX"),
    "XLP": ("XLP", "FDFAX"),
    "XLU": ("XLU", "FSUTX"),
    "XLB": ("XLB", "FSDPX"),
    "XLRE": ("XLRE", "FRESX"),
}


def yahoo(symbol: str) -> pl.DataFrame:
    path = CACHE / f"{symbol}.csv"
    if not path.exists():
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?period1=0&period2=1800000000&interval=1d&events=div,split")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r = json.load(urllib.request.urlopen(req))["chart"]["result"][0]
        price = r["indicators"]["adjclose"][0]["adjclose"]
        # Yahoo stamps daily bars at the session open in exchange time; the date is what counts.
        days = [datetime.fromtimestamp(t + r["meta"]["gmtoffset"], timezone.utc).date()
                for t in r["timestamp"]]
        CACHE.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"date": days, "price": price}).drop_nulls().write_csv(path)
        time.sleep(0.5)
    return pl.read_csv(path, try_parse_dates=True)


def french(industry: str) -> pl.DataFrame:
    path = CACHE / "12_Industry_Portfolios_Daily.csv"
    if not path.exists():
        url = ("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
               "12_Industry_Portfolios_daily_CSV.zip")
        raw = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"})).read()
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(zipfile.ZipFile(io.BytesIO(raw)).read(path.name))
    lines = path.read_text().splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith(",NoDur"))
    # The first block is value-weighted; it ends at the first blank line.
    end = next(i for i in range(head + 1, len(lines)) if not lines[i].strip())
    t = pl.read_csv(io.StringIO("\n".join(lines[head:end])))
    t = t.rename({t.columns[0]: "d"}).select(
        pl.col("d").cast(pl.Utf8).str.strptime(pl.Date, "%Y%m%d").alias("date"),
        (1 + pl.col(industry).cast(pl.Utf8).str.strip_chars().cast(pl.Float64) / 100).cum_prod().alias("price"))
    return t


def series(spec) -> pl.DataFrame:
    if isinstance(spec, list):
        parts = [returns(yahoo(s)).rename({"ret": s}) for s, _ in spec]
        j = parts[0]
        for p in parts[1:]:
            j = j.join(p, on="date")
        mix = sum(pl.col(s) * w for s, w in spec)
        return j.select("date", mix.alias("ret"))
    if spec.startswith("ff:"):
        return returns(french(spec[3:]))
    if spec == "^DJI+yield":
        return returns(yahoo("^DJI")).with_columns(pl.col("ret") + DIA_YIELD / 252)
    return returns(yahoo(spec))


def returns(px: pl.DataFrame) -> pl.DataFrame:
    return px.sort("date").select("date", (pl.col("price") / pl.col("price").shift(1) - 1)
                                  .alias("ret")).drop_nulls()


def build(start: date = START, end: date = END) -> tuple[pl.DataFrame, dict[str, date]]:
    """Wide daily total-return index on NYSE sessions, one column per slot, and each ETF's
    first day. Missing days in a source count as a zero return and are reported by check()."""
    days = nyse_sessions(start, end).select("date")
    out, launch = days, {}
    for slot, (etf, stand_in) in SLOTS.items():
        e = returns(yahoo(etf))
        launch[slot] = yahoo(etf)["date"].min()
        r = e if stand_in is None else pl.concat(
            [series(stand_in).filter(pl.col("date") <= launch[slot]),
             e.filter(pl.col("date") > launch[slot])])
        col = days.join(r, on="date", how="left").with_columns(
            pl.col("ret").fill_null(0.0))["ret"].to_numpy().copy()
        col[0] = 0.0
        out = out.with_columns(pl.Series(slot, 100 * np.cumprod(1 + col)))
    return out, launch


def check():
    days = nyse_sessions(START, END).select("date")
    print(f"{'slot':5} {'stand-in':22} {'ETF from':>11}  overlap  corr  "
          f"{'stand-in':>9} {'ETF':>7}  missing days before launch")
    for slot, (etf, stand_in) in SLOTS.items():
        e = returns(yahoo(etf))
        launch = yahoo(etf)["date"].min()
        if stand_in is None:
            print(f"{slot:5} {'(none)':22} {str(launch):>11}")
            continue
        s = series(stand_in)
        pre = days.filter(pl.col("date") <= launch).join(s, on="date", how="left")
        missing = pre["ret"].null_count()
        j = e.join(s, on="date", suffix="_s").filter(pl.col("date") < date(2025, 1, 1))
        a, b = j["ret"].to_numpy(), j["ret_s"].to_numpy()
        yrs = len(a) / 252
        ga, gb = np.prod(1 + a) ** (1 / yrs) - 1, np.prod(1 + b) ** (1 / yrs) - 1
        name = stand_in if isinstance(stand_in, str) else "+".join(
            f"{w:.0%} {s}" for s, w in stand_in)
        print(f"{slot:5} {name:22} {str(launch):>11}  {yrs:5.1f}y  {np.corrcoef(a, b)[0, 1]:.3f}"
              f"  {gb:8.1%} {ga:7.1%}  {missing}")


if __name__ == "__main__":
    check()
