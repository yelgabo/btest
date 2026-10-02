from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from btest.engine import Config
from btest.sweep import parse_grid, run_sweep


def test_parse_grid_lists_and_inclusive_ranges():
    g = parse_grid(["fast=5,10", "slow=60:180:60", "alloc=0.5:1.0:0.25", "sym=SPY"])
    assert g == {"fast": [5, 10], "slow": [60, 120, 180], "alloc": [0.5, 0.75, 1.0],
                 "sym": ["SPY"]}


def test_sweep_refuses_to_reach_into_holdout():
    with pytest.raises(SystemExit, match="holdout"):
        run_sweep(None, Path("."), Path("x.py"), "SPY", {}, {"fast": [5]},
                  datetime(2016, 1, 1, tzinfo=UTC), datetime(2025, 6, 1, tzinfo=UTC),
                  date(2025, 1, 1), Config())
