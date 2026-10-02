"""Claims lab jobs from Postgres and runs each in a child process with limits. Also keeps the
bars current: a full ingest when the volume is empty, then once each weekday evening."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

import psycopg
import psycopg.conninfo
import psycopg.sql

from btest import config, db, store
from btest.child import RESULT
from btest.ingest import ingest, log
from btest.sources.alpaca import AlpacaSource

TIMEOUT_S = {"run": 300, "sweep": 900}
LOG_CHARS = 6000
INGEST_HOUR_UTC = 22


MEM_LIMIT_MB = int(os.environ.get("BTEST_CHILD_MEM_MB", "0"))


def rss_mb(pid: int) -> float | None:
    """Resident memory of a process from /proc (Linux only; None elsewhere)."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


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
    timeout = TIMEOUT_S[job["kind"]]
    proc = subprocess.Popen(
        [sys.executable, "-m", "btest.child"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, env=child_env(),
    )
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.append(proc.stdout.read()), daemon=True)
    reader.start()
    proc.stdin.write(json.dumps(job, default=str))
    proc.stdin.close()
    started = time.monotonic()
    killed = None
    peak = 0.0
    while proc.poll() is None:
        if time.monotonic() - started > timeout:
            limit = f"{timeout // 60} minutes" if timeout >= 60 else f"{timeout} seconds"
            killed = f"Stopped after {limit}, the limit for a {job['kind']}."
        mem = rss_mb(proc.pid) or 0.0
        peak = max(peak, mem)
        if MEM_LIMIT_MB and mem > MEM_LIMIT_MB:
            killed = f"Stopped at {mem:,.0f} MB of memory; the limit is {MEM_LIMIT_MB:,} MB."
        if killed:
            proc.kill()
            break
        time.sleep(0.2)
    proc.wait()
    reader.join(5)
    out = "".join(chunks)
    if killed:
        return {"error": killed, "log": out}
    result = None
    for line in out.splitlines():
        if line.startswith(RESULT):
            result = json.loads(line[len(RESULT):])
    if result is None:
        reason = (f"killed by signal {-proc.returncode}" if proc.returncode < 0
                  else f"exit code {proc.returncode}")
        result = {"error": f"The run crashed ({reason}). The output below has details."}
    lines = [ln for ln in out.splitlines() if not ln.startswith(RESULT)]
    if peak:
        lines.append(f"peak memory {peak:,.0f} MB")
    result["log"] = "\n".join(lines)
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
