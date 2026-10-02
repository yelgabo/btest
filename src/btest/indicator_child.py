"""Computes one custom indicator. Started by the worker with no database URL or secrets; the
code and the candles arrive on stdin and the lines leave on stdout."""

import importlib.util
import inspect
import json
import math
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np

from btest.child import RESULT, error_line
from btest.indicator import Indicator

MAX_LINES = 8


def load_class(path: Path) -> type[Indicator]:
    spec = importlib.util.spec_from_file_location(f"btest_ind_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [o for _, o in inspect.getmembers(module, inspect.isclass)
             if issubclass(o, Indicator) and o is not Indicator and o.__module__ == module.__name__]
    if len(found) != 1:
        raise ValueError(f"Expected one Indicator subclass, found {len(found)}.")
    return found[0]


def clean(values, n: int, name: str) -> list:
    arr = np.asarray(values, dtype=float).ravel()
    if len(arr) != n:
        raise ValueError(f"Line {name!r} has {len(arr)} values for {n} candles.")
    return [None if not math.isfinite(v) else round(float(v), 6) for v in arr]


def main() -> None:
    job = json.loads(sys.stdin.read())
    c = job["candles"]
    arrays = {"t": np.asarray(c["t"], dtype=np.int64)}
    for key, name in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
        arrays[name] = np.asarray(c[key], dtype=float)
    n = len(arrays["t"])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / (job["name"].rsplit("/", 1)[-1] + ".py")
        path.write_text(job["code"])
        try:
            cls = load_class(path)
            out = cls(**job["params"]).compute(arrays)
            if not isinstance(out, dict) or not out:
                raise ValueError("compute() must return a dict of {line_name: array}.")
            if len(out) > MAX_LINES:
                raise ValueError(f"compute() returned {len(out)} lines; the limit is {MAX_LINES}.")
            series = {str(k): clean(v, n, k) for k, v in out.items()}
        except Exception as e:
            traceback.print_exc()
            line = getattr(e, "lineno", None) if isinstance(e, SyntaxError) else None
            print(RESULT + json.dumps({"error": f"{type(e).__name__}: {e}",
                                       "error_line": line or error_line(e.__traceback__, str(path))}),
                  flush=True)
            sys.exit(1)
    print(RESULT + json.dumps({"series": series}), flush=True)


if __name__ == "__main__":
    main()
