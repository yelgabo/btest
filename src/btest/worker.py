"""Claims lab jobs from Postgres and runs each in a child process with limits. Also keeps the
bars current: a full ingest when the volume is empty, then once each weekday evening."""

import os
import socket
import sys
import threading
import time
from datetime import UTC, datetime

import psycopg
import psycopg.conninfo
import psycopg.sql

from btest import config, db, store
from btest.ingest import ingest, log
from btest.worker_proc import run_child
from btest.sources.alpaca import AlpacaSource

TIMEOUT_S = {"run": 300, "sweep": 900}
LOG_CHARS = 6000
INGEST_HOUR_UTC = 22


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ALPACA_", "BTEST_UI_PASSWORD", "PG", "POSTGRES"))}
    # The child gets the restricted role when one is configured.
    env["DATABASE_URL"] = os.environ.get("BTEST_RUNNER_DATABASE_URL") or os.environ["DATABASE_URL"]
    env.pop("BTEST_RUNNER_DATABASE_URL", None)
    # Polars and numba size their thread pools to the host's CPUs, which on a shared machine is
    # far more than this container gets.
    env.setdefault("POLARS_MAX_THREADS", "4")
    env.setdefault("NUMBA_NUM_THREADS", "4")
    return env


def grant_runner(conn: psycopg.Connection) -> None:
    """Keep the child's role limited to reading market data and writing results. Re-run at
    every start so tables added by later migrations are covered."""
    url = os.environ.get("BTEST_RUNNER_DATABASE_URL")
    if not url:
        return
    role = psycopg.conninfo.conninfo_to_dict(url)["user"]
    for sql in (
        "GRANT USAGE ON SCHEMA market, runs TO {r}",
        "GRANT SELECT ON ALL TABLES IN SCHEMA market TO {r}",
        "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA runs TO {r}",
        "GRANT USAGE ON ALL SEQUENCES IN SCHEMA runs TO {r}",
    ):
        conn.execute(psycopg.sql.SQL(sql).format(r=psycopg.sql.Identifier(role)))
    conn.commit()
    log(f"runner role {role}: grants refreshed")


def claim(conn: psycopg.Connection, worker: str) -> dict | None:
    row = conn.execute(
        "UPDATE lab.job SET status = 'running', started_at = now(), worker = %s WHERE id = ("
        " SELECT id FROM lab.job WHERE status = 'queued' ORDER BY id "
        " FOR UPDATE SKIP LOCKED LIMIT 1) "
        "RETURNING id, kind, spec, strategy_version_id", (worker,),
    ).fetchone()
    conn.commit()
    if row is None:
        return None
    code, version, name = conn.execute(
        "SELECT v.code, v.version, s.name FROM lab.strategy_version v "
        "JOIN lab.strategy s ON s.id = v.strategy_id WHERE v.id = %s", (row[3],),
    ).fetchone()
    # End the read transaction now; left open, finish()'s now() would be the claim time.
    conn.commit()
    return {"id": row[0], "kind": row[1], "spec": row[2], "strategy_version_id": row[3],
            "code": code, "version": version, "name": name}


def execute(job: dict) -> dict:
    result, log = run_child([sys.executable, "-m", "btest.child"], job,
                            TIMEOUT_S[job["kind"]], child_env(), job["kind"])
    result["log"] = log
    return result


def finish(conn: psycopg.Connection, jid: int, result: dict) -> None:
    conn.execute(
        "UPDATE lab.job SET status = %s, finished_at = now(), error = %s, error_line = %s, "
        "log = %s, run_id = %s, sweep_id = %s WHERE id = %s",
        ("failed" if result.get("error") else "done", result.get("error"),
         result.get("error_line"), (result.get("log") or "")[-LOG_CHARS:],
         result.get("run_id"), result.get("sweep_id"), jid),
    )
    conn.commit()


def ingest_loop(settings, stop: threading.Event) -> None:
    last_day = None
    while not stop.is_set():
        now = datetime.now(UTC)
        missing = any(store.last_ts(settings.data_dir, s) is None for s in settings.symbols)
        due = now.weekday() < 5 and now.hour >= INGEST_HOUR_UTC and last_day != now.date()
        if settings.alpaca_key and (missing or due):
            try:
                with psycopg.connect(settings.database_url) as conn:
                    ingest(conn, AlpacaSource(settings.alpaca_key, settings.alpaca_secret),
                           settings.data_dir, settings.symbols, settings.history_start)
                last_day = now.date()
            except Exception as e:
                log(f"ingest failed: {type(e).__name__}: {e}")
        stop.wait(600)


def bars_app(settings):
    """Candles for the web service, which has no bar files of its own. Only reachable on the
    private network, and only with the shared token."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from btest import bars

    token = os.environ.get("BTEST_INTERNAL_TOKEN", "")

    async def candles(request):
        if not token or request.headers.get("x-btest-token") != token:
            return JSONResponse({"error": "Forbidden."}, status_code=403)
        q = request.query_params
        symbol = q.get("symbol", "").upper()
        try:
            start, end = bars.check(symbol, q.get("start", ""), q.get("end", ""), q.get("tf", ""),
                                    settings.symbols)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        with psycopg.connect(settings.database_url) as conn:
            splits, dividends = db.get_splits(conn, symbol), db.get_dividends(conn, symbol)
        return JSONResponse(bars.candles(settings.data_dir, symbol, start, end, q.get("tf"),
                                         splits, dividends))

    def indicator(request_body: dict):
        from btest import indicator_run
        symbol = str(request_body.get("symbol", "")).upper()
        try:
            start, end = bars.check(symbol, request_body.get("start", ""),
                                    request_body.get("end", ""), request_body.get("tf", ""),
                                    settings.symbols)
        except ValueError as e:
            return 400, {"error": str(e)}
        out = indicator_run.series(settings, lambda: psycopg.connect(settings.database_url),
                                   request_body["code"], request_body["name"],
                                   request_body.get("params") or {}, symbol, start, end,
                                   request_body["tf"])
        return (422 if out.get("error") else 200), out

    async def indicator_route(request):
        if not token or request.headers.get("x-btest-token") != token:
            return JSONResponse({"error": "Forbidden."}, status_code=403)
        from starlette.concurrency import run_in_threadpool
        status, out = await run_in_threadpool(indicator, await request.json())
        return JSONResponse(out, status_code=status)

    return Starlette(routes=[Route("/bars", candles),
                             Route("/indicator", indicator_route, methods=["POST"])])


def serve_bars(settings) -> None:
    import uvicorn
    port = int(os.environ.get("BTEST_BARS_PORT", "8081"))
    # "::" so Railway's IPv6 private network can reach it.
    uvicorn.run(bars_app(settings), host="::", port=port, log_level="warning")


def run(poll_s: float = 1.0) -> None:
    settings = config.load(need_alpaca=False)
    worker = f"{socket.gethostname()}:{os.getpid()}"
    host = socket.gethostname()
    with psycopg.connect(settings.database_url) as conn:
        db.migrate(conn)
        grant_runner(conn)
        stale = conn.execute(
            "UPDATE lab.job SET status = 'failed', finished_at = now(), "
            "error = 'The worker restarted while this was running. Run it again.' "
            "WHERE status = 'running' AND worker LIKE %s RETURNING id", (host + ":%",),
        ).fetchall()
        conn.commit()
        if stale:
            log(f"marked {len(stale)} interrupted job(s) failed")
    stop = threading.Event()
    threading.Thread(target=ingest_loop, args=(settings, stop), daemon=True).start()
    if os.environ.get("BTEST_INTERNAL_TOKEN"):
        threading.Thread(target=serve_bars, args=(settings,), daemon=True).start()
    log(f"worker {worker} ready, data in {settings.data_dir}")
    while True:
        try:
            with psycopg.connect(settings.database_url) as conn:
                while True:
                    job = claim(conn, worker)
                    if job is None:
                        time.sleep(poll_s)
                        continue
                    log(f"job {job['id']}: {job['kind']} {job['name']} v{job['version']}")
                    t0 = time.perf_counter()
                    result = execute(job)
                    finish(conn, job["id"], result)
                    log(f"job {job['id']}: {'failed' if result.get('error') else 'done'} "
                        f"in {time.perf_counter() - t0:.1f}s")
        except psycopg.OperationalError as e:
            log(f"database connection lost ({e}); retrying in 5s")
            time.sleep(5)
