import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import psycopg


def write_report(conn: psycopg.Connection, run_id: int, out_dir: Path) -> Path:
    row = conn.execute(
        "SELECT strategy, params, symbols, start_ts, end_ts, config, git_commit, git_dirty, "
        "metrics, benchmark_metrics FROM runs.run WHERE id = %s", (run_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"no run {run_id}")
    equity = conn.execute(
        "SELECT date, equity, benchmark FROM runs.equity WHERE run_id = %s ORDER BY date",
        (run_id,),
    ).fetchall()
    data = {
        "params": row[1],
        "symbols": row[2],
        "start": _utc(row[3]),
        "end": _utc(row[4]),
        "config": row[5],
        "git_commit": row[6],
        "git_dirty": row[7],
        "metrics": row[8],
        "benchmark_metrics": row[9] or {},
        "equity": [[d.isoformat(), round(e, 2), None if b is None else round(b, 2)]
                   for d, e, b in equity],
    }
    template = resources.files("btest.templates").joinpath("report.html").read_text()
    # "</" inside the JSON would let data close the script tag early.
    payload = json.dumps(data).replace("</", "<\\/")
    html = (template.replace("__DATA__", payload)
            .replace("__RUN_ID__", str(run_id))
            .replace("__STRATEGY__", _escape(row[0])))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"run-{run_id}.html"
    path.write_text(html)
    return path


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _utc(ts: datetime) -> str:
    ts = ts.astimezone(UTC)
    return ts.strftime("%Y-%m-%d" if (ts.hour, ts.minute) == (0, 0) else "%Y-%m-%d %H:%M")
