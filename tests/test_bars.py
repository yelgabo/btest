from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from btest import bars, store
from btest.sources.base import BAR_SCHEMA, Split


def write_day(data_dir, day: date, open_utc_hour: int, price: float, minutes: int = 390):
    start = datetime(day.year, day.month, day.day, open_utc_hour, 30, tzinfo=UTC)
    rows = [(start + timedelta(minutes=m), price + m, price + m + 1, price + m - 1, price + m + 0.5,
             10, 1, price + m) for m in range(minutes)]
    df = pl.DataFrame(rows, schema=BAR_SCHEMA, orient="row").with_columns(
        pl.lit(True).alias("regular"))
    store.write_bars(data_dir, "SPY", df)


def test_candles_group_on_new_york_session_time(tmp_path):
    write_day(tmp_path, date(2024, 1, 2), 14, 100.0)   # EST: open 14:30 UTC
    write_day(tmp_path, date(2024, 7, 2), 13, 200.0)   # EDT: open 13:30 UTC
    out = bars.candles(tmp_path, "SPY", date(2024, 1, 1), date(2024, 7, 3), "1h", [], [])
    assert len(out["t"]) == 14
    first = out["t"][0]
    assert datetime.fromtimestamp(first, UTC) == datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    assert out["o"][0] == 100.0 and out["c"][0] == 100.0 + 59 + 0.5
    assert out["h"][0] == 100.0 + 59 + 1 and out["l"][0] == 99.0
    assert out["v"][0] == 600
    summer = [datetime.fromtimestamp(t, UTC).hour for t in out["t"][7:]]
    assert summer[0] == 13 and len(summer) == 7
    daily = bars.candles(tmp_path, "SPY", date(2024, 1, 1), date(2024, 7, 3), "1D", [], [])
    assert len(daily["t"]) == 2 and daily["v"] == [3900, 3900]


def test_candles_carry_adjustment_factor_for_fills(tmp_path):
    write_day(tmp_path, date(2024, 6, 7), 13, 1000.0)
    write_day(tmp_path, date(2024, 6, 10), 13, 100.0)
    out = bars.candles(tmp_path, "SPY", date(2024, 6, 7), date(2024, 6, 10), "1D",
                       [Split(date(2024, 6, 10), 1, 10, "s")], [])
    assert out["f"] == pytest.approx([0.1, 1.0])
    assert out["o"][0] == pytest.approx(100.0)


def test_check_rejects_bad_input_and_huge_requests():
    syms = ["SPY"]
    assert bars.check("SPY", "2024-01-01", "2024-02-01", "5m", syms)
    for args, msg in [(("TSLA", "2024-01-01", "2024-02-01", "5m"), "Symbol"),
                      (("SPY", "2024-01-01", "2024-02-01", "2m"), "Timeframe"),
                      (("SPY", "2024-02-01", "2024-01-01", "5m"), "before"),
                      (("SPY", "2016-01-01", "2025-01-01", "1m"), "candles")]:
        with pytest.raises(ValueError, match=msg):
            bars.check(*args, syms)


def test_worker_bar_service_needs_token(monkeypatch):
    from starlette.testclient import TestClient

    from btest.config import Settings
    from btest.worker import bars_app
    monkeypatch.setenv("BTEST_INTERNAL_TOKEN", "t0k")
    app = bars_app(Settings("", "", "", None, ["SPY"], date(2016, 1, 1), date(2025, 1, 1)))
    c = TestClient(app)
    q = "/bars?symbol=SPY&start=2024-01-01&end=2024-01-02&tf=1D"
    assert c.get(q).status_code == 403
    assert c.get(q, headers={"X-Btest-Token": "wrong"}).status_code == 403
    r = c.get(q.replace("tf=1D", "tf=2m"), headers={"X-Btest-Token": "t0k"})
    assert r.status_code == 400 and "Timeframe" in r.json()["error"]
