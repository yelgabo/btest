"""Start a child process, feed it JSON, and watch its time and memory."""

import json
import os
import subprocess
import threading
import time

from btest.child import RESULT

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


def run_child(argv: list[str], payload: dict, timeout: int, env: dict,
              what: str) -> tuple[dict, str]:
    """Returns (result, log). The result is the child's last RESULT line, or an error saying
    why there was none."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.append(proc.stdout.read()), daemon=True)
    reader.start()
    try:
        proc.stdin.write(json.dumps(payload, default=str))
        proc.stdin.close()
    except BrokenPipeError:
        pass
    started = time.monotonic()
    killed = None
    peak = 0.0
    while proc.poll() is None:
        if time.monotonic() - started > timeout:
            limit = f"{timeout // 60} minutes" if timeout >= 60 else f"{timeout} seconds"
            killed = f"Stopped after {limit}, the limit for a {what}."
        mem = rss_mb(proc.pid) or 0.0
        peak = max(peak, mem)
        if MEM_LIMIT_MB and mem > MEM_LIMIT_MB:
            killed = f"Stopped at {mem:,.0f} MB of memory; the limit is {MEM_LIMIT_MB:,} MB."
        if killed:
            proc.kill()
            break
        time.sleep(0.05)
    proc.wait()
    reader.join(5)
    out = "".join(chunks)
    lines = [ln for ln in out.splitlines() if not ln.startswith(RESULT)]
    if peak:
        lines.append(f"peak memory {peak:,.0f} MB")
    log = "\n".join(lines)
    if killed:
        return {"error": killed}, log
    result = None
    for line in out.splitlines():
        if line.startswith(RESULT):
            result = json.loads(line[len(RESULT):])
    if result is None:
        reason = (f"killed by signal {-proc.returncode}" if proc.returncode < 0
                  else f"exit code {proc.returncode}")
        result = {"error": f"The {what} crashed ({reason}). The output below has details."}
    return result, log
