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


def print_summary(run_id: int, stats: dict, bench: dict, duration: float,
                  timeframe: str = "1m") -> None:
    print(f"run {run_id} ({duration:.1f}s, {timeframe} bars)")
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
    p.add_argument("--cash", type=float, default=None,
                   help="default $100,000 (decide() strategies: $20,000)")
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--commission-per-share", type=float, default=0.0)
    p.add_argument("--sec-fee-rate", type=float, default=Costs().sec_fee_rate,
                   help="fraction of sell notional; default is the current SEC rate")
    p.add_argument("--allow-short", action="store_true")


def _config(args) -> Config:
    return Config(cash=args.cash if args.cash is not None else 100_000.0,
                  allow_short=args.allow_short, costs=Costs(
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
    p_lh = sub.add_parser("longhist", help="download Yahoo day bars from 1995 into Postgres")
    p_lh.add_argument("symbols", nargs="*",
                      help="load only these symbols, keeping the rest; default: every btest.toml symbol")
    p_ing = sub.add_parser("ingest", help="backfill or update bars and corporate actions")
    p_ing.add_argument("symbols", nargs="*", help="defaults to btest.toml symbols")
    p_opt = sub.add_parser("ingest-options",
                           help="fetch monthly puts and their 30-minute bars into Postgres")
    p_opt.add_argument("underlyings", nargs="+")
    p_opt.add_argument("--start", default="2024-02-01", help="first expiry to fetch")
    p_opt.add_argument("--end", default=None, help="last expiry; defaults to 90 days ahead")
    p_live = sub.add_parser("live", help="deploy lab strategies to Alpaca paper trading")
    live_sub = p_live.add_subparsers(dest="live_cmd", required=True)
    p_dep = live_sub.add_parser("deploy", help="create a (disabled) deployment")
    p_dep.add_argument("name")
    p_dep.add_argument("strategy", help="lab strategy name, e.g. portfolio/trend_gtaa")
    p_dep.add_argument("--version", type=int, help="defaults to the latest")
    p_dep.add_argument("--capital", type=float, default=20_000.0)
    p_dep.add_argument("-p", "--param", type=_param, action="append", default=[])
    live_sub.add_parser("list", help="deployments, their last decisions and recent events")
    for name in ("enable", "disable"):
        live_sub.add_parser(name).add_argument("name")
    p_dec = live_sub.add_parser("decide", help="dry run: today's targets and orders, no trades")
    p_dec.add_argument("name")
    p_dec.add_argument("--session", help="a past session to decide on, e.g. 2026-10-02")
    live_sub.add_parser("configure-account",
                        help="apply cash-account settings (no margin, no shorting) to the "
                             "paper account")
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
    p_run.add_argument("symbols", nargs="*",
                       help="symbols to load; decide() strategies default to their universe")
    p_run.add_argument("--no-fractional", action="store_true",
                       help="decide() strategies: whole shares only")
    p_run.add_argument("--no-cash-yield", action="store_true",
                       help="decide() strategies: idle cash earns nothing")
    p_run.add_argument("--benchmark", default="SPY", choices=["SPY", "60/40"])
    p_run.add_argument("--data", default="btest", choices=["btest", "longhist", "longhist_open"],
                       help="decide() strategies: longhist runs on daily bars from 1995, deciding "
                            "on the close; longhist_open decides on the open")
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

        from btest.ui.server import check_exposure, create_app
        app = create_app()
        check_exposure(args.host)
        print(f"btest UI on http://{args.host}:{args.port}", flush=True)
        # Uvicorn reads the client address from X-Forwarded-For only on connections from
        # BTEST_FORWARDED_ALLOW_IPS. Any client can send that header, so trusting every peer
        # would let it pick its own address and dodge the per-address login limit. On Railway
        # set it to the address range Railway's proxy connects from.
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                    proxy_headers=True,
                    forwarded_allow_ips=os.environ.get("BTEST_FORWARDED_ALLOW_IPS") or "127.0.0.1")
        return
    settings = config.load(need_alpaca=args.cmd in ("ingest", "check-adjust", "ingest-options",
                                                     "live"))
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
        if args.cmd == "live":
            live_command(conn, settings, args)
            return
        if args.cmd == "longhist":
            from btest import longhist
            from btest.ingest import sync_risk_free
            rows = longhist.build(args.symbols or settings.symbols, date.today())
            longhist.store(conn, rows, replace_all=not args.symbols)
            sync_risk_free(conn, longhist.START)
            print(f"longhist: {rows.height} rows, {rows['symbol'].n_unique()} symbols, "
                  f"{rows['date'].min()} to {rows['date'].max()}")
            return
        if args.cmd == "coverage":
            for symbol in settings.symbols:
                record_coverage(conn, settings.data_dir, symbol)
            return
        source = AlpacaSource(settings.alpaca_key, settings.alpaca_secret)
        symbols = getattr(args, "symbols", None) or settings.symbols
        if args.cmd == "ingest":
            ingest(conn, source, settings.data_dir, symbols, settings.history_start)
        elif args.cmd == "ingest-options":
            from datetime import timedelta

            from btest.options import ingest_options
            last = (date.fromisoformat(args.end) if args.end
                    else date.today() + timedelta(days=90))
            for u in args.underlyings:
                closes = loader.daily_closes(settings.data_dir, u.upper())
                if closes.is_empty():
                    raise SystemExit(f"no bars for {u}; add it to btest.toml and ingest first")
                ingest_options(conn, source, u.upper(), date.fromisoformat(args.start), last,
                               closes)
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
                extra={"fractional": not args.no_fractional,
                       "cash_yield": not args.no_cash_yield, "benchmark": args.benchmark,
                       "data": args.data}
                | ({"cash": args.cash} if args.cash is not None else {}),
            )
            print_summary(run_id, stats, bench, stats["engine_s"],
                          getattr(load_strategy_class(args.strategy), "timeframe", "1m"))
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


def live_command(conn, settings, args) -> None:
    from btest import live
    from btest.broker import CASH_ACCOUNT, AlpacaBroker
    broker = AlpacaBroker(settings.alpaca_key, settings.alpaca_secret, paper=True)
    if args.live_cmd == "deploy":
        dep_id = live.deploy(conn, args.name, args.strategy, args.version, args.capital,
                             dict(args.param))
        print(f"deployment {dep_id} created, disabled. Enable with: btest live enable {args.name}")
    elif args.live_cmd in ("enable", "disable"):
        if args.live_cmd == "enable":
            n = int(live.enable(conn, args.name))
        else:
            n = conn.execute("UPDATE live.deployment SET enabled = false, updated_at = now() "
                             "WHERE name = %s", (args.name,)).rowcount
        conn.commit()
        print(f"{args.name}: {args.live_cmd}d" if n else f"no deployment {args.name}")
    elif args.live_cmd == "list":
        for d in live.deployments(conn, only_enabled=False):
            print(f"{d.name}: {d.strategy_name} v{d.version}, ${d.capital:,.0f}, {d.mode}, "
                  f"{'enabled' if d.enabled else 'disabled'}")
            for r in conn.execute("SELECT session, status, error FROM live.decision WHERE "
                                  "deployment_id = %s ORDER BY session DESC LIMIT 5", (d.id,)):
                print(f"  {r[0]} {r[1]}{' ' + r[2] if r[2] else ''}")
        for r in conn.execute("SELECT ts, level, message FROM live.event "
                              "ORDER BY id DESC LIMIT 10"):
            print(f"{r[0]:%Y-%m-%d %H:%M} {r[1]}: {r[2]}")
    elif args.live_cmd == "configure-account":
        print(broker.configure(CASH_ACCOUNT))
    elif args.live_cmd == "decide":
        [dep] = [d for d in live.deployments(conn, only_enabled=False) if d.name == args.name] or [
            None]
        if dep is None:
            raise SystemExit(f"no deployment {args.name}")
        session = (date.fromisoformat(args.session) if args.session else
                   datetime.now(UTC).date())
        universe = live._universe_of(dep.code)
        account = live.account_state(broker, universe)
        result = live.run_decision(dep, account, session)
        if result.get("error"):
            print(result.get("log", ""))
            raise SystemExit(f"decision failed: {result['error']}")
        print(json.dumps({k: result[k] for k in ("session", "as_of", "targets", "equity")},
                         indent=2, default=str))
        targets = result["targets"] or {"weights": {}}
        prices = {s: p for s, p in result["prices"].items() if p is not None}
        exits, orders = live.plan_stock_orders(targets["weights"], account["stocks"], prices,
                                               live.strategy_equity(dep, account), 1.0)
        print("orders it would send (dollars; sells first):")
        for s in sorted(exits):
            print(f"  sell all {s}")
        for s, v in sorted(orders.items(), key=lambda kv: kv[1]):
            print(f"  {'buy ' if v > 0 else 'sell'} {s} ${abs(v):,.2f}")
        for s, q in (targets.get("options") or {}).items():
            print(f"  option {s}: target {q} contracts")

