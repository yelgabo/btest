import argparse
from datetime import UTC, datetime

import polars as pl

from btest import config, db, loader
from btest.check import check_adjustments
from btest.ingest import ingest
from btest.sources.alpaca import AlpacaSource


def _utc(s: str) -> datetime:
    ts = datetime.fromisoformat(s)
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(prog="btest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    p_ing = sub.add_parser("ingest", help="backfill or update bars and corporate actions")
    p_ing.add_argument("symbols", nargs="*", help="defaults to btest.toml symbols")
    p_chk = sub.add_parser("check-adjust", help="compare our adjusted bars with Alpaca's")
    p_chk.add_argument("symbols", nargs="*")
    p_bars = sub.add_parser("bars", help="print adjusted regular-session bars")
    p_bars.add_argument("symbol")
    p_bars.add_argument("start", help="UTC, e.g. 2024-06-07T19:55")
    p_bars.add_argument("end")
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
        elif args.cmd == "bars":
            bars = loader.load_bars(settings.data_dir, args.symbol, _utc(args.start),
                                    _utc(args.end), db.get_splits(conn, args.symbol),
                                    db.get_dividends(conn, args.symbol))
            with pl.Config(tbl_rows=50, tbl_cols=-1):
                print(bars)
