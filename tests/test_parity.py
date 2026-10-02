from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl

from btest.config import ROOT
from btest.engine import Config, Costs
from btest.parity import compare
from btest.runner import load_strategy_class
from btest.sources.base import Dividend, Split

MA = load_strategy_class(ROOT / "strategies" / "ma_cross.py")


def synthetic(days=40, per_day=60, seed=7):
    """Random-walk minute bars with a 4:1 split on day 15 and a dividend on day 25."""
    rng = np.random.default_rng(seed)
    rows = []
    price = 400.0
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    for d in range(days):
        day = start + timedelta(days=d)
        if d == 15:
            price /= 4
        for m in range(per_day):
            o = price
            price *= 1 + rng.normal(0, 0.002)
            ts = day + timedelta(minutes=m)
            rows.append((ts, ts.date(), o, price))
    df = pl.DataFrame(rows, schema={"ts": pl.Datetime("us", "UTC"), "date": pl.Date,
                                    "raw_open": pl.Float64, "raw_close": pl.Float64},
                      orient="row")
    split_day = (start + timedelta(days=15)).date()
    adj = pl.when(pl.col("date") < split_day).then(0.25).otherwise(1.0)
    df = df.with_columns(
        (pl.col("raw_open") * adj).alias("open"), (pl.col("raw_close") * adj).alias("close"),
    ).with_columns(
        pl.max_horizontal("open", "close").alias("high"),
        pl.min_horizontal("open", "close").alias("low"),
        pl.lit(100.0).alias("volume"),
    )
    splits = [Split(split_day, 1, 4, "s")]
    dividends = [Dividend((start + timedelta(days=25)).date(), 0.5, False, "d")]
    return df, splits, dividends


CFG = Config(cash=50_000.0, costs=Costs(slippage_bps=2, commission_per_share=0.005,
                                        sec_fee_rate=0.0000278))


def test_ma_cross_fast_path_matches_event_engine_exactly():
    bars, splits, divs = synthetic()
    for fast, slow in [(5, 30), (10, 60), (3, 120)]:
        r = compare(MA, {"fast": fast, "slow": slow, "symbol": "X", "allocation": 0.9}, "X",
                    bars, splits, divs, CFG)
        assert r.event_fills > 10
        assert r.ok, r


class Peeking(MA):
    def signals(self, a):
        w = super().signals(a)
        return np.append(w[1:], np.nan)


def test_parity_catches_a_signal_that_reads_the_next_bar():
    bars, splits, divs = synthetic()
    r = compare(Peeking, {"fast": 5, "slow": 30, "symbol": "X"}, "X", bars, splits, divs, CFG)
    assert not r.ok


ZSCORE = load_strategy_class(ROOT / "strategies" / "mean_reversion" / "zscore.py")


def test_zscore_fast_path_matches_event_engine_exactly():
    bars, splits, divs = synthetic()
    for window, entry, exit_ in [(30, 1.5, 0.0), (60, 2.0, 0.5)]:
        r = compare(ZSCORE, {"symbol": "X", "window": window, "entry_z": entry, "exit_z": exit_},
                    "X", bars, splits, divs, CFG)
        assert r.event_fills > 10
        assert r.ok, r
