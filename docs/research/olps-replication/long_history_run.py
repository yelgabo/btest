"""Monthly CWMR (lab olps/cwmr_monthly, unchanged) on the long_history series.

Daily closes only, so the strategy decides on each session's close and fills at that close;
btest's live timing decides at 15:30 and fills at 15:45. Pass "validate" to run 2016-2024,
where every slot is the real ETF, for comparison with btest's 18.3% (SPY 13.8%)."""
import io
import math
import sys
import urllib.request
from datetime import date
from math import erf
from pathlib import Path

import numpy as np
import polars as pl

from btest import metrics
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import load_strategy_class
sys.path.insert(0, str(Path(__file__).parent))
from long_history import CACHE, build  # noqa: E402

PRICE_COLS = ("open", "high", "low", "close", "raw_close", "fill", "cut_open", "cut_high",
              "cut_low", "cut_close", "raw_cut_close")


def tbill() -> pl.DataFrame:
    path = CACHE / "DTB3.csv"
    if not path.exists():
        path.write_bytes(urllib.request.urlopen(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3").read())
    t = pl.read_csv(path, try_parse_dates=True, null_values=".")
    return t.select(pl.col(t.columns[0]).alias("date"),
                    pl.col("DTB3").cast(pl.Float64).alias("rate")).drop_nulls()


def setup(start: date, end: date):
    wide, launch = build(start, end)
    dates = wide["date"].to_list()
    frames = {s: pl.DataFrame({"date": dates, **{c: wide[s] for c in PRICE_COLS},
                               "volume": np.full(len(dates), 1e9),
                               "cut_volume": np.full(len(dates), 1e9)})
              for s in wide.columns[1:]}
    sessions = nyse_sessions(start, date(end.year + 1, 3, 1))
    return Market(dates, frames), sessions, launch


def paired(eq1, eq2):
    j = eq1.join(eq2, on="date", suffix="_b").sort("date")
    r1 = np.diff(j["equity"].to_numpy()) / j["equity"].to_numpy()[:-1]
    r2 = np.diff(j["equity_b"].to_numpy()) / j["equity_b"].to_numpy()[:-1]
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / len(r1)
    z = (s1 - s2) / math.sqrt(var)
    return (s1 - s2) * math.sqrt(252), 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2))))


def control(start: date, end: date):
    """Added after the pre-registered run: monthly equal weight in the same 16 slots, to
    separate the algorithm's effect from the stand-ins' returns."""
    market, sessions, _ = setup(start, end)
    rates = tbill()
    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.7))
    crp = load_strategy_class(Path("strategies/olps/crp.py"))
    cwmr = load_strategy_class(Path("strategies/olps/cwmr_monthly.py"))
    eqs = {}
    for name, cls in (("Monthly CWMR", cwmr), ("Monthly CRP", crp)):
        r = PortfolioEngine(market, sessions, cfg, rates=rates).run(cls(), start, end)
        eqs[name] = r.equity
        st = metrics.compute(r.equity, rates)
        print(f"  {name:13} CAGR {st['cagr']:6.2%}  Sharpe {st['sharpe']:.2f}  "
              f"max DD {st['max_drawdown']:6.1%}")
    d, p = paired(eqs["Monthly CWMR"], eqs["Monthly CRP"])
    print(f"  paired Sharpe CWMR vs CRP {d:+.2f} (no rf), p {p:.2f}")
    for lo, hi in ((start, date(1999, 1, 1)), (date(1999, 1, 1), end)):
        part = {k: v.filter((pl.col("date") >= lo) & (pl.col("date") < hi)) for k, v in eqs.items()}
        yrs = part["Monthly CRP"].height / 252
        g = {k: (v["equity"][-1] / v["equity"][0]) ** (1 / yrs) - 1 for k, v in part.items()}
        print(f"  {lo} to {hi}: " + ", ".join(f"{k} {x:.1%}" for k, x in g.items()))


def main(start: date, end: date, costs_bp=(0.7, 5, 10, 20)):
    market, sessions, launch = setup(start, end)
    rates = tbill()
    cwmr = load_strategy_class(Path("strategies/olps/cwmr_monthly.py"))
    spy = load_strategy_class(Path("strategies/baseline/buy_hold.py"))
    print(f"{start} to {end}; ETFs replace stand-ins on: "
          + ", ".join(f"{s} {d}" for s, d in launch.items() if d > start))
    for bp in costs_bp:
        cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=bp))
        runs = {}
        for name, cls in (("Monthly CWMR", cwmr), ("SPY", spy)):
            r = PortfolioEngine(market, sessions, cfg, rates=rates).run(cls(), start, end)
            runs[name] = (r.equity, metrics.compute(r.equity, rates)
                          | metrics.trade_stats(r.fills, r.equity))
        d, p = paired(runs["Monthly CWMR"][0], runs["SPY"][0])
        print(f"\n{bp} bp per dollar traded")
        for name, (_, st) in runs.items():
            print(f"  {name:13} CAGR {st['cagr']:6.2%}  Sharpe {st['sharpe']:.2f}  "
                  f"max DD {st['max_drawdown']:6.1%}  turnover {st['turnover']:4.1f}x")
        print(f"  paired Sharpe vs SPY {d:+.2f} (no rf), p {p:.2f}")


if __name__ == "__main__":
    if sys.argv[1:] == ["control"]:
        control(date(1995, 1, 3), date(2016, 1, 1))
    elif sys.argv[1:] == ["validate"]:
        main(date(2016, 1, 1), date(2025, 1, 1), costs_bp=(0.7,))
    else:
        main(date(1995, 1, 3), date(2016, 1, 1))
