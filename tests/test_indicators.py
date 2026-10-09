import json
import os
import sys
from datetime import date

import numpy as np
import pytest

from btest import indicator_run, lab
from btest.config import ROOT, Settings
from btest.worker_proc import run_child
from tests.test_lab import TEST_DB, synthetic_spy, testdb  # noqa: F401

RSI = (ROOT / "indicators" / "rsi.py").read_text()


def candles(n=300, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0, 0.002, n))
    t = 1_700_000_000 + 60 * np.arange(n)
    return {"t": t.tolist(), "o": close.tolist(), "h": (close + 0.1).tolist(),
            "l": (close - 0.1).tolist(), "c": close.tolist(), "v": [100] * n}


def child(code, params=None, c=None):
    return run_child([sys.executable, "-m", "btest.indicator_child"],
                     {"code": code, "name": "x", "params": params or {}, "candles": c or candles()},
                     20, indicator_run.child_env(), "indicator")


def test_inspect_indicator_settings():
    info = lab.inspect_code(RSI, "indicator")
    assert (info.class_name, info.params, info.pane, info.levels) == ("RSI", {"length": 14},
                                                                     "own", [30, 70])
    assert "compute" in lab.inspect_code(
        "from btest.indicator import Indicator\nclass A(Indicator):\n    pass\n", "indicator").error


def test_child_computes_lines_without_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://should-not-leak")
    out, _ = child(RSI, {"length": 14})
    rsi = out["series"]["rsi"]
    assert len(rsi) == 300 and rsi[:14] == [None] * 14
    assert all(0 <= v <= 100 for v in rsi[14:])
    leak = RSI.replace('return {"rsi": rsi}', 'import os; return {"env": [len(os.environ.get("DATABASE_URL", ""))] * len(close)}')
    out, _ = child(leak)
    assert set(out["series"]["env"]) == {0}


def test_child_reports_errors_with_lines():
    bad = RSI.replace("avg_gain = (avg_gain", "avg_gain = (undefined_name")
    line = next(i for i, ln in enumerate(bad.splitlines(), 1) if "undefined_name" in ln)
    out, _ = child(bad)
    assert out["error"].startswith("NameError") and out["error_line"] == line
    short = RSI.replace('return {"rsi": rsi}', 'return {"rsi": rsi[:5]}')
    out, _ = child(short)
    assert "5 values for 300 candles" in out["error"]


def test_starter_indicators_run():
    for f in ("zscore.py", "vwap.py"):
        out, log = child((ROOT / "indicators" / f).read_text(), {"length": 30} if f == "zscore.py" else {})
        assert "series" in out, log
        line = next(iter(out["series"].values()))
        assert len(line) == 300 and line[-1] is not None


def test_series_loads_warmup_and_trims(tmp_path, monkeypatch):
    synthetic_spy(tmp_path)
    monkeypatch.setattr(indicator_run.db, "get_splits", lambda c, s: [])
    monkeypatch.setattr(indicator_run.db, "get_dividends", lambda c, s: [])

    class Null:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    settings = Settings("", "", "", tmp_path, ["SPY"], date(2016, 1, 1), date(2025, 1, 1))
    out = indicator_run.series(settings, Null, RSI, "rsi", {"length": 14}, "SPY",
                               date(2020, 1, 8), date(2020, 1, 9), "15m")
    assert len(out["t"]) == 2 * 26 and out["pane"] == "own"
    assert out["series"]["rsi"][0] is not None


def test_web_indicator_endpoint(testdb, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from btest.ui import server
    synthetic_spy(tmp_path)
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setenv("BTEST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BTEST_UI_PASSWORD", "pw-ind")
    monkeypatch.delenv("BTEST_BARS_URL", raising=False)
    c = TestClient(server.create_app(), base_url="https://testserver", client=("10.0.0.9", 1))
    c.post("/login", data={"password": "pw-ind"})
    h = {"X-Btest": "1"}
    created = c.post("/api/strategies", json={"name": "osc/rsi", "kind": "indicator"}, headers=h)
    assert created.status_code == 201, created.text
    iid = created.json()["id"]
    assert [x["kind"] for x in c.get("/api/strategies").json() if x["id"] == iid] == ["indicator"]
    r = c.post("/api/jobs", headers=h, json={"strategy_id": iid, "kind": "run", "spec": {}})
    assert r.status_code == 400 and "chart" in r.json()["error"]
    q = "symbol=SPY&start=2020-01-08&end=2020-01-09&tf=15m&params=" + json.dumps({"length": 5})
    r = c.get(f"/api/indicators/{iid}/series?{q}")
    assert r.status_code == 200, r.text
    assert r.json()["params"] == {"length": 5} and len(r.json()["series"]["rsi"]) == 52


def script(code, timeout=20, env=None):
    return run_child([sys.executable, "-c", code], {}, timeout,
                     env or indicator_run.child_env(), "test")


@pytest.mark.parametrize("line, why", [
    ("BTEST_RESULT {not json", "not JSON"),
    ("BTEST_RESULT [1, 2]", "expected an object"),
    ('BTEST_RESULT {"error": 5}', "error has the wrong type"),
    ('BTEST_RESULT {"run_id": "7"}', "run_id has the wrong type"),
    ('BTEST_RESULT {"series": {"a": 1}}', "series values must be lists"),
])
def test_malformed_result_fails_the_job(line, why):
    out, _ = script(f"print({line!r})")
    assert out["error"].startswith("The test sent back a malformed result") and why in out["error"]


def test_timeout_kills_grandchildren_too():
    code = ("import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(p.pid, flush=True)\n"
            "time.sleep(60)\n")
    out, log = script(code, timeout=1)
    assert out["error"] == "Stopped after 1 seconds, the limit for a test."
    pid = int(log.splitlines()[0])
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        import time
        time.sleep(0.05)
    os.kill(pid, 9)
    raise AssertionError("grandchild survived")


def test_cpu_limit_and_output_cap(monkeypatch):
    from btest import worker_proc
    assert worker_proc.cpu_limit_s(300, {"POLARS_MAX_THREADS": "4", "NUMBA_NUM_THREADS": "2"}) \
        == 1210
    monkeypatch.setattr(worker_proc, "MAX_OUTPUT_CHARS", 100_000)
    out, log = script("import sys\nfor _ in range(50): sys.stdout.write('x' * 9999 + '\\n')\n"
                      "print('BTEST_RESULT {\"run_id\": 3}')")
    assert out == {"run_id": 3} and 0 < len(log) <= 100_000


def test_run_child_closes_its_pipes():
    import gc
    import warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out, _ = script("print('BTEST_RESULT {}')")
        gc.collect()
    assert out == {}
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_cpu_limit_stops_a_busy_child(monkeypatch):
    from btest import worker_proc
    monkeypatch.setattr(worker_proc, "cpu_limit_s", lambda timeout, env: 1)
    out, _ = script("while True: pass", timeout=20)
    assert out["error"].startswith("The test crashed (it used up its CPU time).")
