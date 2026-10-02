import json
from datetime import UTC, date, datetime
from importlib import resources

import duckdb
import psycopg
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from btest import config
from btest.store import bars_dir

STATIC = resources.files("btest.ui") / "static"
SUMMARY_KEYS = ["total_return", "cagr", "sharpe", "sortino", "max_drawdown", "ann_vol",
                "fills", "exposure", "win_rate", "turnover", "costs", "end_equity"]


def _json_default(v):
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(v, date):
        return v.isoformat()
    raise TypeError(f"not JSON serializable: {type(v).__name__}")


class JSON(Response):
    media_type = "application/json"

    def render(self, content) -> bytes:
        return json.dumps(content, default=_json_default, allow_nan=False).encode()


def _clean(v):
    """JSON has no NaN or infinity; send null instead."""
    if isinstance(v, float) and v != v or v in (float("inf"), float("-inf")):
        return None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def create_app() -> Starlette:
    settings = config.load()
    holdout = datetime.combine(settings.holdout_start, datetime.min.time(), UTC)

    def conn() -> psycopg.Connection:
        return psycopg.connect(settings.database_url)

    async def runs(request: Request):
        with conn() as c:
            rows = c.execute(
                "SELECT id, created_at, strategy, symbols, start_ts, end_ts, params, metrics, "
                "benchmark_metrics, git_commit, git_dirty FROM runs.run ORDER BY id DESC"
            ).fetchall()
        return JSON(_clean([{
            "id": r[0], "created_at": r[1], "strategy": r[2], "symbols": r[3],
            "start": r[4], "end": r[5], "params": r[6],
            "metrics": {k: r[7].get(k) for k in SUMMARY_KEYS},
            "benchmark": {k: (r[8] or {}).get(k) for k in SUMMARY_KEYS},
            "git_commit": r[9], "git_dirty": r[10], "holdout": r[5] > holdout,
        } for r in rows]))

    async def run_detail(request: Request):
        run_id = request.path_params["id"]
        with conn() as c:
            r = c.execute(
                "SELECT id, created_at, strategy, strategy_sha256, symbols, start_ts, end_ts, "
                "params, config, metrics, benchmark_metrics, git_commit, git_dirty, duration_s "
                "FROM runs.run WHERE id = %s", (run_id,),
            ).fetchone()
            if r is None:
                return JSON({"error": f"No run {run_id}."}, status_code=404)
            equity = c.execute(
                "SELECT date, equity, benchmark FROM runs.equity WHERE run_id = %s ORDER BY date",
                (run_id,),
            ).fetchall()
            fill_count = c.execute("SELECT count(*) FROM runs.fill WHERE run_id = %s",
                                   (run_id,)).fetchone()[0]
            fills = c.execute(
                "SELECT ts, symbol, qty, price, slippage + fees + commission, realized_pnl "
                "FROM runs.fill WHERE run_id = %s ORDER BY seq DESC LIMIT 200", (run_id,),
            ).fetchall()
        return JSON(_clean({
            "id": r[0], "created_at": r[1], "strategy": r[2], "strategy_sha256": r[3],
            "symbols": r[4], "start": r[5], "end": r[6], "params": r[7], "config": r[8],
            "metrics": r[9], "benchmark": r[10] or {}, "git_commit": r[11], "git_dirty": r[12],
            "duration_s": r[13], "holdout": r[6] > holdout,
            "equity": [[d, round(e, 2), None if b is None else round(b, 2)] for d, e, b in equity],
            "monthly": monthly_returns(equity),
            "fill_count": fill_count,
            "fills": [list(f) for f in fills],
        }))

    async def sweeps(request: Request):
        with conn() as c:
            rows = c.execute(
                "SELECT s.id, s.created_at, s.strategy, s.symbol, s.start_ts, s.end_ts, s.grid, "
                "s.fixed_params, s.combos, s.skipped, s.duration_s, "
                "(SELECT max((r.metrics->>'sharpe')::float) FROM runs.sweep_result r "
                " WHERE r.sweep_id = s.id) FROM runs.sweep s ORDER BY s.id DESC"
            ).fetchall()
        return JSON(_clean([{
            "id": r[0], "created_at": r[1], "strategy": r[2], "symbol": r[3], "start": r[4],
            "end": r[5], "grid": r[6], "fixed": r[7], "combos": r[8], "skipped": r[9],
            "duration_s": r[10], "best_sharpe": r[11],
        } for r in rows]))

    async def sweep_detail(request: Request):
        sweep_id = request.path_params["id"]
        with conn() as c:
            s = c.execute(
                "SELECT id, created_at, strategy, symbol, start_ts, end_ts, holdout_start, grid, "
                "fixed_params, config, combos, skipped, duration_s, git_commit, git_dirty "
                "FROM runs.sweep WHERE id = %s", (sweep_id,),
            ).fetchone()
            if s is None:
                return JSON({"error": f"No sweep {sweep_id}."}, status_code=404)
            results = c.execute(
                "SELECT params, metrics FROM runs.sweep_result WHERE sweep_id = %s ORDER BY seq",
                (sweep_id,),
            ).fetchall()
        return JSON(_clean({
            "id": s[0], "created_at": s[1], "strategy": s[2], "symbol": s[3], "start": s[4],
            "end": s[5], "holdout_start": s[6], "grid": s[7], "fixed": s[8], "config": s[9],
            "combos": s[10], "skipped": s[11], "duration_s": s[12], "git_commit": s[13],
            "git_dirty": s[14],
            "results": [{"params": p, "metrics": m} for p, m in results],
        }))

    async def data(request: Request):
        with conn() as c:
            actions = c.execute(
                "SELECT y.ticker, "
                "(SELECT count(*) FROM market.split s WHERE s.symbol_id = y.id), "
                "(SELECT count(*) FROM market.dividend d WHERE d.symbol_id = y.id), "
                "(SELECT json_agg(json_build_object('ex_date', s.ex_date, 'ratio', "
                " s.new_rate / s.old_rate) ORDER BY s.ex_date) FROM market.split s "
                " WHERE s.symbol_id = y.id), "
                "(SELECT max(d.ex_date) FROM market.dividend d WHERE d.symbol_id = y.id) "
                "FROM market.symbol y ORDER BY y.ticker"
            ).fetchall()
            rate = c.execute("SELECT date, value FROM market.rate WHERE series = 'DTB3' "
                             "ORDER BY date DESC LIMIT 1").fetchone()
        symbols = []
        with duckdb.connect() as db:
            db.execute("SET TimeZone = 'UTC'")
            for ticker, n_splits, n_divs, split_list, last_div in actions:
                files = bars_dir(settings.data_dir, ticker) / "year=*" / "bars.parquet"
                try:
                    n, regular, first, last = db.execute(
                        # Formatted in SQL: returning timestamptz to Python would need pytz.
                        f"SELECT count(*), count(*) FILTER (WHERE regular), "
                        f"strftime(min(ts), '%Y-%m-%dT%H:%M:%SZ'), "
                        f"strftime(max(ts), '%Y-%m-%dT%H:%M:%SZ') FROM read_parquet('{files}')"
                    ).fetchone()
                except duckdb.IOException:
                    n, regular, first, last = 0, 0, None, None
                symbols.append({
                    "symbol": ticker, "bars": n, "regular_bars": regular, "first": first,
                    "last": last, "splits": split_list or [], "dividends": n_divs,
                    "last_dividend": last_div,
                })
        return JSON({
            "symbols": symbols,
            "holdout_start": settings.holdout_start,
            "history_start": settings.history_start,
            "risk_free": {"series": "DTB3", "date": rate[0], "value": rate[1]} if rate else None,
        })

    async def index(request: Request):
        return FileResponse(STATIC / "index.html")

    return Starlette(routes=[
        Route("/", index),
        Route("/api/runs", runs),
        Route("/api/runs/{id:int}", run_detail),
        Route("/api/sweeps", sweeps),
        Route("/api/sweeps/{id:int}", sweep_detail),
        Route("/api/data", data),
        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
    ])


def monthly_returns(equity: list[tuple]) -> list[list]:
    """[year, month, return] from month-end equity; the first month is measured from the
    first day's equity."""
    out = []
    prev = equity[0][1] if equity else None
    for i, (d, e, _) in enumerate(equity):
        nxt = equity[i + 1][0] if i + 1 < len(equity) else None
        if nxt is None or (nxt.year, nxt.month) != (d.year, d.month):
            out.append([d.year, d.month, e / prev - 1 if prev else None])
            prev = e
    return out
