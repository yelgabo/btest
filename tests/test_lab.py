import json
import os
import subprocess
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import psycopg
import pytest

from btest import db, lab, store
from btest.config import Settings
from btest.sources.base import BAR_SCHEMA

TEST_DB = "postgresql://localhost:5432/btest_test"

SETTINGS = Settings("", "", TEST_DB, None, ["SPY", "META"], date(2016, 1, 1), date(2025, 1, 1))


def test_inspect_reads_params_and_signals_without_running():
    info = lab.inspect_code(lab.EXAMPLE)
    assert info.class_name == "BuyAndHold"
    assert info.params == {"symbol": "SPY", "allocation": 1.0}
    assert info.has_signals and info.error is None


def test_inspect_reports_syntax_error_line():
    info = lab.inspect_code("from btest.strategy import Strategy\n\nclass A(Strategy)\n    pass\n")
    assert info.error.startswith("SyntaxError") and info.error_line == 3


def test_inspect_needs_exactly_one_strategy_class():
    assert "found 0" in lab.inspect_code("x = 1\n").error


def test_names_are_paths():
    assert lab.check_name("Trend/MA_Cross.py") == "trend/ma_cross"
    with pytest.raises(ValueError):
        lab.check_name("bad name")


def spec(**kw):
    base = {"symbols": "spy", "start": "2016-01-01", "end": "2024-01-01", "params": {"fast": 5}}
    return base | kw


def test_run_spec_normalises_and_guards_holdout():
    out = lab.validate_spec("run", spec(), SETTINGS, False)
    assert out["symbols"] == ["SPY"] and out["params"] == {"fast": 5}
    with pytest.raises(ValueError, match="holdout"):
        lab.validate_spec("run", spec(end="2025-06-01"), SETTINGS, False)
    ok = lab.validate_spec("run", spec(end="2025-06-01", spend_holdout=True), SETTINGS, False)
    assert ok["spend_holdout"]
    with pytest.raises(ValueError, match="no data"):
        lab.validate_spec("run", spec(symbols="TSLA"), SETTINGS, False)


def test_sweep_spec_needs_signals_grid_and_limits():
    s = {"symbol": "SPY", "start": "2016-01-01", "end": "2024-01-01",
         "params": {"fast": 5, "slow": 50}, "grid": {"fast": "5,10", "slow": "20:40:10"}}
    out = lab.validate_spec("sweep", s, SETTINGS, True)
    assert out["grid"] == {"fast": [5, 10], "slow": [20, 30, 40]} and out["params"] == {}
    with pytest.raises(ValueError, match="signals"):
        lab.validate_spec("sweep", s, SETTINGS, False)
    with pytest.raises(ValueError, match="limit"):
        lab.validate_spec("sweep", s | {"grid": {"a": "1:100:1", "b": "1:100:1"}}, SETTINGS, True)
    with pytest.raises(ValueError, match="on or before"):
        lab.validate_spec("sweep", s | {"end": "2025-03-01"}, SETTINGS, True)


@pytest.fixture(scope="module")
def testdb():
    try:
        subprocess.run(["dropdb", "--if-exists", "btest_test"], check=True, capture_output=True)
        subprocess.run(["createdb", "btest_test"], check=True, capture_output=True)
        conn = psycopg.connect(TEST_DB)
    except (OSError, subprocess.CalledProcessError, psycopg.OperationalError):
        pytest.skip("local Postgres not available")
    db.migrate(conn)
    yield conn
    conn.close()


def test_save_versions_and_conflicts(testdb):
    sid = lab.create(testdb, "trend/demo", lab.EXAMPLE)
    s = lab.get(testdb, sid)
    assert s["version"] == 1 and s["class_name"] == "BuyAndHold"
    assert lab.save(testdb, sid, s["code"], 1) == 1
    assert lab.save(testdb, sid, s["code"] + "\n# v2\n", 1) == 2
    with pytest.raises(ValueError, match="Reload"):
        lab.save(testdb, sid, s["code"] + "\n# other tab\n", 1)
    with pytest.raises(ValueError, match="clash"):
        lab.create(testdb, "trend/demo/inner")
    lab.rename(testdb, sid, "trend/demo2")
    assert [x["name"] for x in lab.list_strategies(testdb)] == ["trend/demo2"]


def synthetic_spy(data_dir):
    rng = np.random.default_rng(1)
    rows, price = [], 400.0
    start = datetime(2020, 1, 6, 14, 30, tzinfo=UTC)
    for d in range(30):
        for m in range(390):
            o = price
            price *= 1 + rng.normal(0, 0.0005)
            rows.append((start + timedelta(days=d, minutes=m), o, max(o, price), min(o, price),
                         price, 1000, 10, price))
    df = pl.DataFrame(rows, schema=BAR_SCHEMA, orient="row").with_columns(
        pl.lit(True).alias("regular"))
    store.write_bars(data_dir, "SPY", df)


def run_child(job, tmp_path):
    from btest.worker import execute
    env = {"DATABASE_URL": TEST_DB, "BTEST_DATA_DIR": str(tmp_path)}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return execute(job)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_child_runs_a_strategy_and_reports_error_lines(testdb, tmp_path):
    synthetic_spy(tmp_path)
    sid = lab.create(testdb, "child_demo", lab.EXAMPLE)
    s = lab.get(testdb, sid)
    job = {"id": 0, "kind": "run", "strategy_version_id": s["version_id"], "version": 1,
           "name": "child_demo", "code": s["code"],
           "spec": {"symbols": ["SPY"], "start": "2020-01-01", "end": "2020-03-01",
                    "params": {}, "config": {}}}
    ok = run_child(job, tmp_path)
    assert "error" not in ok, ok.get("log")
    row = testdb.execute("SELECT strategy, strategy_version_id, metrics->>'fills' FROM runs.run "
                         "WHERE id = %s", (ok["run_id"],)).fetchone()
    assert row == ("child_demo.py@v1:BuyAndHold", s["version_id"], "1")

    broken = s["code"].replace('ctx.order_target_percent(bar.symbol, self.params["allocation"])',
                               "1 / 0")
    line = next(i for i, ln in enumerate(broken.splitlines(), 1) if "1 / 0" in ln)
    bad = run_child(job | {"code": broken}, tmp_path)
    assert bad["error"] == "ZeroDivisionError: division by zero"
    assert bad["error_line"] == line

    syntax = run_child(job | {"code": "class Oops(:\n"}, tmp_path)
    assert syntax["error"].startswith("SyntaxError") and syntax["error_line"] == 1


def test_web_login_header_guard_and_job_submit(testdb, monkeypatch):
    from starlette.testclient import TestClient

    from btest.ui import server
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setenv("BTEST_UI_PASSWORD", "pw-for-tests")
    app = server.create_app()
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/strategies").status_code == 401
    assert c.get("/", follow_redirects=False).headers["location"] == "/login"
    for _ in range(10):
        assert c.post("/login", data={"password": "nope"}).status_code == 401
    assert c.post("/login", data={"password": "pw-for-tests"}).status_code == 429

    c2 = TestClient(app, base_url="https://testserver", client=("10.0.0.2", 1))
    r = c2.post("/login", data={"password": "pw-for-tests"}, follow_redirects=False)
    assert r.status_code == 303 and "btest_session" in r.cookies
    assert c2.post("/api/strategies", json={"name": "web_demo"}).status_code == 403
    h = {"X-Btest": "1"}
    sid = c2.post("/api/strategies", json={"name": "web_demo"}, headers=h).json()["id"]
    got = c2.get(f"/api/strategies/{sid}").json()
    assert got["params"] == {"symbol": "SPY", "length": 20, "allocation": 1.0}
    r = c2.post("/api/jobs", headers=h, json={"strategy_id": sid, "kind": "run", "spec": {
        "symbols": "SPY", "start": "2016-01-01", "end": "2025-06-01"}})
    assert r.status_code == 400 and "holdout" in r.json()["error"]
    r = c2.post("/api/jobs", headers=h, json={"strategy_id": sid, "kind": "run", "spec": {
        "symbols": "SPY", "start": "2016-01-01", "end": "2024-01-01"}})
    jid = r.json()["id"]
    j = c2.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "queued" and j["spec"]["symbols"] == ["SPY"]


def test_worker_kills_a_job_over_its_time_limit(testdb, tmp_path, monkeypatch):
    from btest import worker
    synthetic_spy(tmp_path)
    sid = lab.create(testdb, "slow_demo", lab.EXAMPLE)
    s = lab.get(testdb, sid)
    slow = s["code"].replace("    def on_bar(self, ctx, bar):\n",
                             "    def on_bar(self, ctx, bar):\n        import time; time.sleep(5)\n")
    monkeypatch.setitem(worker.TIMEOUT_S, "run", 1)
    job = {"id": 0, "kind": "run", "strategy_version_id": s["version_id"], "version": 1,
           "name": "slow_demo", "code": slow,
           "spec": {"symbols": ["SPY"], "start": "2020-01-01", "end": "2020-03-01",
                    "params": {}, "config": {}}}
    out = run_child(job, tmp_path)
    assert out["error"] == "Stopped after 1 seconds, the limit for a run."


def test_longhist_runs_decide_strategies_from_1995_on_its_own_symbols():
    universe = ["SPY", "META"]
    s = spec(start="1995-01-03", config={"data": "longhist"})
    out = lab.validate_spec("run", s, SETTINGS, False, universe)
    assert out["symbols"] == universe and out["config"]["data"] == "longhist"
    assert out["start"] == "1995-01-03"
    with pytest.raises(ValueError, match="Data starts 2016"):
        lab.validate_spec("run", spec(start="1995-01-03"), SETTINGS, False, universe)
    with pytest.raises(ValueError, match="TLT has no data"):
        lab.validate_spec("run", s, SETTINGS, False, ["SPY", "TLT"])
    with pytest.raises(ValueError, match="decide"):
        lab.validate_spec("run", s, SETTINGS, False)
