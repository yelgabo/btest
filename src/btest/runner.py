import hashlib
import importlib.util
import inspect
import subprocess
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars as pl
import psycopg

from btest import bars, db, loader, metrics
from btest.config import ROOT
from btest.engine import Config, Engine, Result
from btest.strategy import Strategy, has_decide

BENCHMARK = "SPY"


def load_strategy_class(path: Path) -> type[Strategy]:
    spec = importlib.util.spec_from_file_location(f"btest_user_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [obj for _, obj in inspect.getmembers(module, inspect.isclass)
             if issubclass(obj, Strategy) and obj is not Strategy
             and obj.__module__ == module.__name__]
    if len(found) != 1:
        raise SystemExit(f"{path}: expected exactly one Strategy subclass, found {len(found)}")
    return found[0]


def strategy_timeframe(cls: type[Strategy]) -> str:
    tf = getattr(cls, "timeframe", "1m")
    if tf not in bars.TIMEFRAMES:
        raise SystemExit(f"{cls.__name__}.timeframe is {tf!r}; use one of "
                         f"{', '.join(bars.TIMEFRAMES)}.")
    return tf


def daily_close(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.group_by("date").agg(pl.col("close").sort_by("ts").last()).sort("date")


def benchmark_equity(bars: pl.DataFrame, dates: pl.Series, cash: float) -> pl.DataFrame:
    """Buy-and-hold on adjusted closes, which include reinvested dividends."""
    closes = daily_close(bars)
    out = pl.DataFrame({"date": dates}).join(closes, on="date", how="left")
    out = out.with_columns(pl.col("close").forward_fill().backward_fill())
    first = out["close"][0]
    return out.select("date", (pl.col("close") / first * cash).alias("benchmark"))


def _git() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "strategies"],
                               cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip() != ""
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def run_backtest(conn: psycopg.Connection, data_dir: Path, strategy_path: Path, params: dict,
                 symbols: list[str], start: datetime, end: datetime, config: Config,
                 label: str | None = None,
                 strategy_version_id: int | None = None,
                 extra: dict | None = None) -> tuple[int, dict, dict, Result]:
    cls = load_strategy_class(strategy_path)
    if has_decide(cls):
        return run_portfolio(conn, data_dir, strategy_path, params, symbols, start, end,
                             portfolio_config(config, extra), label, strategy_version_id)
    if (extra or {}).get("data", "btest") != "btest":
        raise SystemExit("Long-history data is daily closes; it runs decide() strategies only.")
    strategy = cls(**params)
    tf = strategy_timeframe(cls)
    splits = {s: db.get_splits(conn, s) for s in symbols}
    dividends = {s: db.get_dividends(conn, s) for s in symbols}
    data = {s: bars.aggregate(loader.load_bars(data_dir, s, start, end, splits[s], dividends[s]), tf)
            for s in symbols}
    for s, df in data.items():
        if df.is_empty():
            raise SystemExit(f"no bars for {s} in {start} to {end}; run `btest ingest {s}`")

    t0 = time.perf_counter()
    result = Engine(data, config, splits, dividends).run(strategy)
    duration = time.perf_counter() - t0

    bench_bars = data.get(BENCHMARK)
    if bench_bars is None:
        bench_bars = loader.load_bars(data_dir, BENCHMARK, start, end,
                                      db.get_splits(conn, BENCHMARK),
                                      db.get_dividends(conn, BENCHMARK))
    equity = result.equity.join(
        benchmark_equity(bench_bars, result.equity["date"], config.cash), on="date", how="left",
    )
    rf = db.get_rates(conn, "DTB3")
    stats = metrics.compute(equity, rf) | metrics.trade_stats(result.fills, equity) | {
        "exposure": result.exposure, "bars": result.bars, "engine_s": duration,
    }
    bench = metrics.compute(equity.select("date", pl.col("benchmark").alias("equity")), rf)
    # Lab strategies are versioned in the database, so the repo commit says nothing about them.
    commit, dirty = _git() if strategy_version_id is None else (None, None)
    run_id = db.save_run(conn, {
        "strategy": f"{label or strategy_path.name}:{cls.__name__}",
        "strategy_sha256": hashlib.sha256(strategy_path.read_bytes()).hexdigest(),
        "params": strategy.params,
        "symbols": symbols,
        "start_ts": start,
        "end_ts": end,
        "config": config.to_dict() | {"timeframe": tf},
        "git_commit": commit,
        "git_dirty": dirty,
        "metrics": stats,
        "benchmark_metrics": bench,
        "duration_s": duration,
        "strategy_version_id": strategy_version_id,
    }, result.fills, equity)
    return run_id, stats, bench, result


def benchmark_from_daily(frames: dict[str, pl.DataFrame], name: str, dates: pl.Series,
                         cash: float) -> pl.DataFrame:
    """Buy-and-hold SPY, or SPY/AGG 60/40 rebalanced at each month end, on adjusted closes."""
    weights = {"SPY": {"SPY": 1.0}, "60/40": {"SPY": 0.6, "AGG": 0.4}}[name]
    out = pl.DataFrame({"date": dates})
    for s in weights:
        out = out.join(frames[s].select("date", pl.col("close").alias(s)), on="date", how="left")
    out = out.with_columns(pl.col(s).forward_fill().backward_fill() for s in weights)
    values = []
    units: dict[str, float] = {}
    for k, row in enumerate(out.iter_rows(named=True)):
        if k == 0:
            units = {s: cash * w / row[s] for s, w in weights.items()}
        value = sum(units[s] * row[s] for s in weights)
        values.append(value)
        last_of_month = k + 1 == out.height or out["date"][k + 1].month != row["date"].month
        if last_of_month and len(weights) > 1:
            units = {s: value * w / row[s] for s, w in weights.items()}
    return pl.DataFrame({"date": dates, "benchmark": values})


DATA_SOURCES = ("btest", "longhist", "longhist_open")


def portfolio_config(config: Config, extra: dict | None = None):
    from btest.portfolio import PortfolioConfig, PortfolioCosts
    extra = extra or {}
    benchmark = extra.get("benchmark", "SPY")
    if benchmark not in ("SPY", "60/40"):
        raise SystemExit("benchmark must be SPY or 60/40")
    if extra.get("data", "btest") not in DATA_SOURCES:
        raise SystemExit(f"data must be one of {', '.join(DATA_SOURCES)}")
    return PortfolioConfig(
        cash=float(extra.get("cash", PortfolioConfig().cash)),
        data=extra.get("data", "btest"),
        costs=PortfolioCosts(slippage_bps=config.costs.slippage_bps,
                             sec_fee_rate=config.costs.sec_fee_rate),
        fractional=bool(extra.get("fractional", True)),
        cash_yield=bool(extra.get("cash_yield", True)),
        benchmark=benchmark,
    )


def run_portfolio(conn: psycopg.Connection, data_dir: Path, strategy_path: Path, params: dict,
                  symbols: list[str] | None, start: datetime, end: datetime, pconfig,
                  label: str | None = None,
                  strategy_version_id: int | None = None) -> tuple[int, dict, dict, object]:
    from datetime import date as date_cls

    from btest import daily
    from btest.options import OptionBook
    from btest.portfolio import Market, PortfolioEngine, option_multiplier

    cls = load_strategy_class(strategy_path)
    strategy = cls(**params)
    universe = [s.upper() for s in (symbols or list(getattr(cls, "universe", [])))]
    if not universe:
        raise SystemExit(f"{cls.__name__} has no universe; set universe = [...] or pass symbols")
    first_day, last_day = start.date(), end.date()
    need = list(dict.fromkeys(universe + list({"SPY": ["SPY"], "60/40": ["SPY", "AGG"]}
                                              [pconfig.benchmark])))
    # A strategy can require a data source (its timing depends on it) and set its own costs.
    required = getattr(cls, "data", None)
    if required and pconfig.data != required:
        raise SystemExit(f"{cls.__name__} runs on data {required!r}; pass --data {required}")
    schedule = getattr(cls, "slippage_schedule", None)
    if schedule:
        pconfig = replace(pconfig, costs=replace(pconfig.costs, slippage_schedule=tuple(
            (a, b, tuple(s), bps) for a, b, s, bps in schedule)))
    if pconfig.data in ("longhist", "longhist_open"):
        from btest import longhist
        from btest.calendar import nyse_sessions
        # market.session starts at history_start; this calendar also runs past the last day
        # for month_end / month_position.
        all_sessions = nyse_sessions(longhist.START, date_cls(last_day.year + 2, 1, 1))
        sessions = all_sessions.filter(pl.col("date") < last_day)
        splits, dividends = {}, {}
        frames = longhist.frames(conn, need, last_day,
                                 decide_at="open" if pconfig.data == "longhist_open" else "close")
    else:
        # The full calendar, published a year ahead: the daily cache covers every bar and
        # month_end / month_position see the sessions after a run's last day.
        all_sessions = db.get_sessions(conn, date_cls(2000, 1, 1), date_cls(2100, 1, 1))
        sessions = all_sessions.filter(pl.col("date") < last_day)
        splits = {s: db.get_splits(conn, s) for s in need}
        dividends = {s: db.get_dividends(conn, s) for s in need}
        frames = {}
        for s in need:
            df = daily.load(data_dir, s, all_sessions, pconfig.timing, splits[s], dividends[s])
            if df.is_empty():
                raise SystemExit(f"no bars for {s}; run `btest ingest {s}`")
            frames[s] = df.filter(pl.col("date") < last_day)
    starts = [frames[s]["date"].min() for s in universe]
    dates = [d for d in sessions["date"].to_list() if d >= min(starts)]
    market = Market(dates, {s: frames[s] for s in universe})
    rf = db.get_rates(conn, "DTB3")
    engine = PortfolioEngine(market, all_sessions, pconfig, splits, dividends, rf,
                             None if pconfig.data in ("longhist", "longhist_open") else OptionBook(conn, end))
    t0 = time.perf_counter()
    result = engine.run(strategy, first_day, last_day)
    duration = time.perf_counter() - t0
    if result.equity.is_empty():
        raise SystemExit(f"no sessions between {first_day} and {last_day}")

    equity = result.equity.join(
        benchmark_from_daily(frames, pconfig.benchmark, result.equity["date"], pconfig.cash),
        on="date", how="left")
    stats = metrics.compute(equity, rf) | metrics.trade_stats(
        result.fills, equity, option_multiplier) | {
        "exposure": result.exposure, "bars": result.bars, "engine_s": duration,
        "notes": result.notes[:200],
    }
    bench = metrics.compute(equity.select("date", pl.col("benchmark").alias("equity")), rf)
    commit, dirty = _git() if strategy_version_id is None else (None, None)
    run_id = db.save_run(conn, {
        "strategy": f"{label or strategy_path.name}:{cls.__name__}",
        "strategy_sha256": hashlib.sha256(strategy_path.read_bytes()).hexdigest(),
        "params": strategy.params,
        "symbols": universe,
        "start_ts": start,
        "end_ts": end,
        "config": pconfig.to_dict() | {"timeframe": "1D", "engine": "portfolio",
                                       "rebalance": getattr(cls, "rebalance", "daily")},
        "git_commit": commit,
        "git_dirty": dirty,
        "metrics": stats,
        "benchmark_metrics": bench | {"name": pconfig.benchmark},
        "duration_s": duration,
        "strategy_version_id": strategy_version_id,
    }, result.fills, equity)
    return run_id, stats, bench, result
