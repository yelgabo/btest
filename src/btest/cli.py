import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from btest import config, db, loader
from btest.check import check_adjustments
from btest.engine import Config, Costs
from btest.ingest import ingest
from btest.report import write_report
from btest.runner import run_backtest
from btest.sources.alpaca import AlpacaSource


def _utc(s: str) -> datetime:
    ts = datetime.fromisoformat(s)
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _param(s: str) -> tuple[str, object]:
    key, sep, raw = s.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected key=value, got {s!r}")
    try:
        return key, json.loads(raw)
    except json.JSONDecodeError:
        return key, raw


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.4f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


PCT_KEYS = {"total_return", "cagr", "ann_vol", "max_drawdown", "exposure", "win_rate"}


def print_summary(run_id: int, stats: dict, bench: dict, duration: float) -> None:
    print(f"run {run_id} ({duration:.1f}s)")
    print(f"{'metric':<20}{'strategy':>16}{'SPY buy+hold':>16}")
    for k in ["total_return", "cagr", "ann_vol", "sharpe", "sortino", "max_drawdown",
              "max_drawdown_days", "end_equity", "exposure", "fills", "win_rate", "turnover",
              "costs"]:
        row = []
        for src in (stats, bench):
            v = src.get(k)
            row.append(f"{v:.2%}" if k in PCT_KEYS and v is not None else _fmt(v))
        print(f"{k:<20}{row[0]:>16}{row[1] if k in bench else '':>16}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="btest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    p_ing = sub.add_parser("ingest", help="backfill or update bars and corporate actions")
    p_ing.add_argument("symbols", nargs="*", help="defaults to btest.toml symbols")
    p_chk = sub.add_parser("check-adjust", help="compare our adjusted bars with Alpaca's")
    p_chk.add_argument("symbols", nargs="*")
    p_rep = sub.add_parser("report", help="write the HTML report for a run")
    p_rep.add_argument("run_id", type=int)
    p_bars = sub.add_parser("bars", help="print adjusted regular-session bars")
    p_bars.add_argument("symbol")
    p_bars.add_argument("start", help="UTC, e.g. 2024-06-07T19:55")
    p_bars.add_argument("end")
    p_run = sub.add_parser("run", help="backtest a strategy file")
    p_run.add_argument("strategy", type=Path)
    p_run.add_argument("symbols", nargs="+")
    p_run.add_argument("--start", required=True, help="UTC date or datetime")
    p_run.add_argument("--end", required=True, help="exclusive")
    p_run.add_argument("-p", "--param", type=_param, action="append", default=[],
                       help="strategy param, e.g. -p fast=30")
    p_run.add_argument("--cash", type=float, default=100_000.0)
    p_run.add_argument("--slippage-bps", type=float, default=1.0)
    p_run.add_argument("--commission-per-share", type=float, default=0.0)
    p_run.add_argument("--sec-fee-rate", type=float, default=0.0)
    p_run.add_argument("--allow-short", action="store_true")
    args = parser.parse_args()

    settings = config.load()
    with db.connect(settings.database_url) as conn:
        if args.cmd == "migrate":
            print("applied:", db.migrate(conn) or "nothing new")
            return
        db.migrate(conn)
        source = AlpacaSource(settings.alpaca_key, settings.alpaca_secret)
        symbols = getattr(args, "symbols", None) or settings.symbols
        if args.cmd == "ingest":
            ingest(conn, source, settings.data_dir, symbols, settings.history_start)
        elif args.cmd == "check-adjust":
            report = check_adjustments(conn, source, settings.data_dir, symbols)
            with pl.Config(tbl_rows=-1):
                print(report.group_by("symbol").agg(
                    pl.len().alias("days"),
                    pl.col("matched").sum(),
                    (pl.col("ours") - pl.col("theirs")).abs().sum().alias("count_diff"),
                    pl.col("max_rel_err").max(),
                    pl.col("max_rel_err").median().alias("median_rel_err"),
                ).sort("symbol"))
                worst = report.sort("max_rel_err", descending=True, nulls_last=True).head(10)
                print(worst)
        elif args.cmd == "run":
            run_config = Config(cash=args.cash, allow_short=args.allow_short, costs=Costs(
                slippage_bps=args.slippage_bps, commission_per_share=args.commission_per_share,
                sec_fee_rate=args.sec_fee_rate,
            ))
            run_id, stats, bench, _ = run_backtest(
                conn, settings.data_dir, args.strategy, dict(args.param), args.symbols,
                _utc(args.start), _utc(args.end), run_config,
            )
            print_summary(run_id, stats, bench, stats["engine_s"])
            print("report:", write_report(conn, run_id, settings.data_dir / "reports"))
        elif args.cmd == "report":
            print(write_report(conn, args.run_id, settings.data_dir / "reports"))
        elif args.cmd == "bars":
            bars = loader.load_bars(settings.data_dir, args.symbol, _utc(args.start),
                                    _utc(args.end), db.get_splits(conn, args.symbol),
                                    db.get_dividends(conn, args.symbol))
            with pl.Config(tbl_rows=50, tbl_cols=-1):
                print(bars)
