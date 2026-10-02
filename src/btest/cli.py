import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from btest import config, db, loader
from btest.check import check_adjustments
from btest.engine import Config, Costs
from btest.ingest import ingest, record_coverage
from btest.report import write_report
from btest.parity import compare
from btest.runner import load_strategy_class, run_backtest
from btest.sweep import parse_grid, run_sweep
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


def _cost_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cash", type=float, default=100_000.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--commission-per-share", type=float, default=0.0)
    p.add_argument("--sec-fee-rate", type=float, default=0.0)
    p.add_argument("--allow-short", action="store_true")


def _config(args) -> Config:
    return Config(cash=args.cash, allow_short=args.allow_short, costs=Costs(
        slippage_bps=args.slippage_bps, commission_per_share=args.commission_per_share,
        sec_fee_rate=args.sec_fee_rate,
    ))


def _warn_holdout(conn, settings, strategy: Path, end: datetime) -> None:
    holdout = datetime.combine(settings.holdout_start, datetime.min.time(), UTC)
    if end <= holdout:
        return
    prior = conn.execute(
        "SELECT count(*) FROM runs.run WHERE strategy LIKE %s AND end_ts > %s",
        (f"{strategy.name}:%", holdout),
    ).fetchone()[0]
    print(f"holdout: this run uses data from {settings.holdout_start} on. "
          f"{prior} earlier run(s) of {strategy.name} already did. Every look at the holdout "
          "spends some of its value as an unbiased test.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="btest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("coverage", help="refresh the bar summary the UI reads from Postgres")
    p_ing = sub.add_parser("ingest", help="backfill or update bars and corporate actions")
    p_ing.add_argument("symbols", nargs="*", help="defaults to btest.toml symbols")
    p_chk = sub.add_parser("check-adjust", help="compare our adjusted bars with Alpaca's")
    p_chk.add_argument("symbols", nargs="*")
    sub.add_parser("worker", help="run lab jobs from the website and keep bars current")
    p_imp = sub.add_parser("import-strategies", help="add strategies/*.py to the website lab")
    p_imp.add_argument("folder", type=Path, nargs="?", default=Path("strategies"))
    p_ui = sub.add_parser("ui", help="serve the local web UI")
    p_ui.add_argument("--host", default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
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
    _cost_args(p_run)
    p_sw = sub.add_parser("sweep", help="fast-path parameter sweep, stopping before the holdout")
    p_sw.add_argument("strategy", type=Path)
    p_sw.add_argument("symbol")
    p_sw.add_argument("--start", required=True)
    p_sw.add_argument("--end", help="exclusive; defaults to holdout_start in btest.toml")
    p_sw.add_argument("-g", "--grid", action="append", required=True,
                      help="fast=5,10,20 or slow=100:400:50 (inclusive)")
    p_sw.add_argument("-p", "--param", type=_param, action="append", default=[])
    p_sw.add_argument("--sort", default="sharpe")
    p_sw.add_argument("--top", type=int, default=15)
    _cost_args(p_sw)
    p_par = sub.add_parser("parity", help="check signals() against on_bar() on real data")
    p_par.add_argument("strategy", type=Path)
    p_par.add_argument("symbol")
    p_par.add_argument("--start", required=True)
    p_par.add_argument("--end", required=True)
    p_par.add_argument("-p", "--param", type=_param, action="append", default=[])
    _cost_args(p_par)
    args = parser.parse_args()

    if args.cmd == "worker":
        from btest.worker import run as run_worker
        run_worker()
        return
    if args.cmd == "ui":
        import uvicorn

        from btest.ui.server import create_app
        print(f"btest UI on http://{args.host}:{args.port}", flush=True)
        uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning",
                    proxy_headers=True, forwarded_allow_ips="*")
        return
    settings = config.load(need_alpaca=args.cmd in ("ingest", "check-adjust"))
    with db.connect(settings.database_url) as conn:
        if args.cmd == "migrate":
            print("applied:", db.migrate(conn) or "nothing new")
            return
        db.migrate(conn)
        if args.cmd == "import-strategies":
            from btest import lab
            added = lab.import_files(conn, args.folder)
            folder = Path("indicators")
            if folder.is_dir():
                added += [f"indicator {n}" for n in lab.import_files(conn, folder, "indicator")]
            print("added:", added or "nothing new")
            return
        if args.cmd == "coverage":
            for symbol in settings.symbols:
                record_coverage(conn, settings.data_dir, symbol)
            return
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
            run_config = _config(args)
            _warn_holdout(conn, settings, args.strategy, _utc(args.end))
            run_id, stats, bench, _ = run_backtest(
                conn, settings.data_dir, args.strategy, dict(args.param), args.symbols,
                _utc(args.start), _utc(args.end), run_config,
            )
            print_summary(run_id, stats, bench, stats["engine_s"])
            print("report:", write_report(conn, run_id, settings.data_dir / "reports"))
        elif args.cmd == "sweep":
            end = _utc(args.end) if args.end else datetime.combine(
                settings.holdout_start, datetime.min.time(), UTC)
            grid = parse_grid(args.grid)
            sweep_id, table = run_sweep(conn, settings.data_dir, args.strategy, args.symbol,
                                        dict(args.param), grid, _utc(args.start), end,
                                        settings.holdout_start, _config(args))
            if table.is_empty():
                print("every combination was skipped")
                return
            cols = list(grid) + ["sharpe", "cagr", "max_drawdown", "total_return", "fills",
                                 "exposure"]
            best = table.sort(args.sort, descending=True, nulls_last=True)
            with pl.Config(tbl_rows=args.top, tbl_cols=-1, float_precision=4):
                print(best.select(cols).head(args.top))
            top = best.row(0, named=True)
            chosen = dict(args.param) | {k: top[k] for k in grid}
            flags = " ".join(f"-p {k}='{json.dumps(v)}'" if isinstance(v, str)
                             else f"-p {k}={json.dumps(v)}" for k, v in chosen.items())
            print(f"sweep {sweep_id}. To confirm the best row once on the holdout:")
            print(f"  uv run btest run {args.strategy} {args.symbol} "
                  f"--start {settings.holdout_start} --end {date.today()} {flags}")
        elif args.cmd == "parity":
            cls = load_strategy_class(args.strategy)
            splits = db.get_splits(conn, args.symbol)
            dividends = db.get_dividends(conn, args.symbol)
            bars = loader.load_bars(settings.data_dir, args.symbol, _utc(args.start),
                                    _utc(args.end), splits, dividends)
            r = compare(cls, dict(args.param), args.symbol, bars, splits, dividends,
                        _config(args))
            print(r)
            print("parity OK" if r.ok else "parity FAILED")
            if not r.ok:
                raise SystemExit(1)
        elif args.cmd == "report":
            print(write_report(conn, args.run_id, settings.data_dir / "reports"))
        elif args.cmd == "bars":
            bars = loader.load_bars(settings.data_dir, args.symbol, _utc(args.start),
                                    _utc(args.end), db.get_splits(conn, args.symbol),
                                    db.get_dividends(conn, args.symbol))
            with pl.Config(tbl_rows=50, tbl_cols=-1):
                print(bars)
