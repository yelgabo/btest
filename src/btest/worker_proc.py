"""Start a child process, feed it JSON, and watch its time and memory."""

import json
import os
import resource
import signal
import subprocess
import threading
import time

from btest.child import RESULT

MEM_LIMIT_MB = int(os.environ.get("BTEST_CHILD_MEM_MB", "0"))
# The worker keeps only the tail of the log, so a child that prints without end must not be
# able to fill the worker's memory.
MAX_OUTPUT_CHARS = 4_000_000
THREAD_VARS = ("POLARS_MAX_THREADS", "NUMBA_NUM_THREADS", "OMP_NUM_THREADS")
RESULT_TYPES = {"error": (str,), "error_line": (int, type(None)), "run_id": (int,),
                "sweep_id": (int,), "series": (dict,), "targets": (dict, type(None)),
                "prices": (dict,)}


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


def cpu_limit_s(timeout: int, env: dict) -> int:
    """RLIMIT_CPU counts every thread's time, so a child running its full thread pool for the
    whole wall-clock limit uses timeout x threads. The limit is a backstop for a child the
    worker can no longer watch, not the normal way a job stops."""
    threads = max((int(env[k]) for k in THREAD_VARS if env.get(k, "").isdigit()),
                  default=os.cpu_count() or 1)
    return timeout * threads + 10


def _limits(cpu_s: int):
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
    return apply


def _popen_limits(cpu_s: int) -> dict:
    # preexec_fn runs Python between fork and exec, which CPython documents as unsafe in a
    # threaded process (the worker has several), and it forces a full fork instead of vfork.
    # Linux can set the limit from outside with prlimit; local macOS runs use preexec_fn.
    return {} if hasattr(resource, "prlimit") else {"preexec_fn": _limits(cpu_s)}


def _drain(stream, chunks: list[str]) -> None:
    size = 0
    while chunk := stream.read(65536):
        chunks.append(chunk)
        size += len(chunk)
        while size > MAX_OUTPUT_CHARS and len(chunks) > 1:
            size -= len(chunks.pop(0))


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def parse_result(out: str) -> dict | None:
    """The last RESULT line, or None if there is none. Raises ValueError if it is malformed."""
    line = None
    for ln in out.splitlines():
        if ln.startswith(RESULT):
            line = ln
    if line is None:
        return None
    try:
        result = json.loads(line[len(RESULT):])
    except ValueError as e:
        raise ValueError(f"not JSON ({e})") from None
    if not isinstance(result, dict):
        raise ValueError(f"expected an object, got {type(result).__name__}")
    for key, types in RESULT_TYPES.items():
        v = result.get(key)
        if key in result and (not isinstance(v, types) or isinstance(v, bool)):
            raise ValueError(f"{key} has the wrong type ({type(v).__name__})")
    series = result.get("series")
    if series is not None and not all(isinstance(v, list) for v in series.values()):
        raise ValueError("series values must be lists")
    return result


def run_child(argv: list[str], payload: dict, timeout: int, env: dict,
              what: str) -> tuple[dict, str]:
    """Returns (result, log). The result is the child's last RESULT line, or an error saying
    why there was none. The child leads its own process group so a kill also reaches anything
    it started."""
    cpu_s = cpu_limit_s(timeout, env)
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env,
                            start_new_session=True, **_popen_limits(cpu_s))
    if hasattr(resource, "prlimit"):
        try:
            resource.prlimit(proc.pid, resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
        except ProcessLookupError:
            pass
    chunks: list[str] = []
    reader = threading.Thread(target=_drain, args=(proc.stdout, chunks), daemon=True)
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
            break
        time.sleep(0.05)
    # Also after a normal exit: a leftover grandchild would hold the pipe open.
    _kill_group(proc.pid)
    proc.wait()
    reader.join(5)
    if not reader.is_alive():
        proc.stdout.close()
    out = "".join(chunks)
    lines = [ln for ln in out.splitlines() if not ln.startswith(RESULT)]
    if peak:
        lines.append(f"peak memory {peak:,.0f} MB")
    log = "\n".join(lines)
    if killed:
        return {"error": killed}, log
    try:
        result = parse_result(out)
    except ValueError as e:
        return {"error": f"The {what} sent back a malformed result: {e}"}, log
    if result is None:
        if proc.returncode == -signal.SIGXCPU:
            reason = "it used up its CPU time"
        elif proc.returncode < 0:
            reason = f"killed by signal {-proc.returncode}"
        else:
            reason = f"exit code {proc.returncode}"
        result = {"error": f"The {what} crashed ({reason}). The output below has details."}
    return result, log
