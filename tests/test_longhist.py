from datetime import date

import polars as pl

from btest import longhist


def test_build_starts_each_symbol_on_its_first_day_and_fills_gaps(monkeypatch):
    px = {"OLD": pl.DataFrame({"date": [date(1995, 1, 3), date(1995, 1, 5)],
                               "close": [10.0, 11.0]}),
          "NEW": pl.DataFrame({"date": [date(1995, 1, 5), date(1995, 1, 6)],
                               "close": [20.0, 21.0]})}
    monkeypatch.setattr(longhist, "yahoo", lambda s: px[s])
    rows = longhist.build(["OLD", "NEW"], date(1995, 1, 9))
    old = rows.filter(pl.col("symbol") == "OLD")
    assert old["date"].to_list() == [date(1995, 1, d) for d in (3, 4, 5, 6)]
    assert old["close"].to_list() == [10.0, 10.0, 11.0, 11.0]
    new = rows.filter(pl.col("symbol") == "NEW")
    assert new["date"].to_list() == [date(1995, 1, 5), date(1995, 1, 6)]


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
