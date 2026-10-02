"""Runs one lab job. The worker starts this in a fresh process, sends the job on stdin and
reads one result line from stdout, so strategy code never runs inside the worker itself."""

import json
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from btest import config
from btest.engine import Config, Costs
from btest.runner import run_backtest
from btest.sweep import run_sweep

RESULT = "BTEST_RESULT "


def _utc(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(tzinfo=UTC)


def _config(c: dict) -> Config:
    return Config(cash=c.get("cash", 100_000.0), allow_short=c.get("allow_short", False),
                  costs=Costs(slippage_bps=c.get("slippage_bps", 1.0),
                              commission_per_share=c.get("commission_per_share", 0.0),
                              sec_fee_rate=c.get("sec_fee_rate", 0.0)))


def error_line(tb, path: str) -> int | None:
    """The deepest traceback frame inside the strategy file, so the editor can point at it."""
    line = None
    for frame in traceback.extract_tb(tb):
        if frame.filename == path:
            line = frame.lineno
    return line


def main() -> None:
    job = json.loads(sys.stdin.read())
    settings = config.load(need_alpaca=False)
    spec = job["spec"]
    leaf = job["name"].rsplit("/", 1)[-1]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{leaf}.py"
        path.write_text(job["code"])
        label = f"{job['name']}.py@v{job['version']}"
        try:
            with psycopg.connect(settings.database_url) as conn:
                if job["kind"] == "run":
                    run_id, *_ = run_backtest(
                        conn, settings.data_dir, path, spec["params"], spec["symbols"],
                        _utc(spec["start"]), _utc(spec["end"]), _config(spec["config"]),
                        label=label, strategy_version_id=job["strategy_version_id"])
                    out = {"run_id": run_id}
                else:
                    sweep_id, _ = run_sweep(
                        conn, settings.data_dir, path, spec["symbol"], spec["params"],
                        spec["grid"], _utc(spec["start"]), _utc(spec["end"]),
                        settings.holdout_start, _config(spec["config"]), label=label,
                        strategy_version_id=job["strategy_version_id"])
                    out = {"sweep_id": sweep_id}
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            traceback.print_exc()
            line = getattr(e, "lineno", None) if isinstance(e, SyntaxError) else None
            message = str(e) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
            out = {"error": message,
                   "error_line": line or error_line(e.__traceback__, str(path))}
            print(RESULT + json.dumps(out), flush=True)
            sys.exit(1)
    print(RESULT + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
