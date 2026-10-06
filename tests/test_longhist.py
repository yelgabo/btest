from datetime import date

import numpy as np
import polars as pl

from btest import longhist
from btest.calendar import nyse_sessions


def series(days, rets):
    return pl.DataFrame({"date": days, "price": 50 * np.cumprod(1 + np.asarray(rets))})


def test_build_splices_the_stand_in_before_launch_and_the_etf_after(monkeypatch):
    days = nyse_sessions(longhist.START, date(1995, 3, 1))["date"].to_list()
    launch = 20
    fund = np.linspace(-0.01, 0.01, len(days))
    etf = np.full(len(days), 0.002)
    prices = {"FUND": series(days, fund), "ETF": series(days[launch:], etf[launch:])}
    monkeypatch.setattr(longhist, "yahoo", lambda s: prices[s])
    monkeypatch.setattr(longhist, "STAND_INS", {"ETF": "FUND"})
    rows = longhist.build(date(1995, 3, 2))
    close = rows["close"].to_numpy()
    got = close[1:] / close[:-1] - 1
    assert np.allclose(got[:launch], fund[1:launch + 1])
    assert np.allclose(got[launch:], etf[launch + 1:])
    assert rows["source"].to_list() == ["FUND"] * (launch + 1) + ["ETF"] * (len(days) - launch - 1)


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args):
        symbols, end = args
        return type("C", (), {"fetchall": lambda _: [r for r in self.rows
                                                     if r[0] in symbols and r[1] < end]})()


def test_frames_put_the_close_in_every_price_column():
    rows = [("SPY", date(1995, 1, 3), 100.0), ("SPY", date(1995, 1, 4), 101.0),
            ("SPY", date(1995, 1, 5), 102.0)]
    f = longhist.frames(FakeConn(rows), ["SPY"], date(1995, 1, 5))["SPY"]
    assert f["date"].to_list() == [date(1995, 1, 3), date(1995, 1, 4)]
    for c in ("close", "cut_close", "fill", "raw_close", "raw_cut_close", "open"):
        assert f[c].to_list() == [100.0, 101.0]
