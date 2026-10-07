import re

from btest import bars, lab
from btest.engine import Context
from btest.fast import arrays
from btest.parity import compare
from btest.strategy import Bar
from tests.test_parity import CFG, synthetic

CODE = lab.TEMPLATE


def test_template_is_the_new_strategy_starting_point_and_parses():
    info = lab.inspect_code(CODE)
    assert info.error is None
    assert (info.class_name, info.timeframe, info.has_signals) == ("MyStrategy", "1D", True)
    assert info.params == {"symbol": "SPY", "length": 20, "allocation": 1.0}


def test_template_runs_and_passes_parity(tmp_path):
    path = tmp_path / "my_strategy.py"
    path.write_text(CODE)
    from btest.runner import load_strategy_class
    cls = load_strategy_class(path)
    minute, splits, divs = synthetic(days=40, per_day=10)
    r = compare(cls, {"symbol": "X"}, "X", minute, splits, divs, CFG)
    assert r.ok and r.event_fills == 0


def test_every_name_the_template_documents_exists():
    for name in set(re.findall(r"ctx\.(\w+)", CODE)):
        assert hasattr(Context, name), f"template mentions ctx.{name}"
    for name in set(re.findall(r"bar\.(\w+)", CODE)) - {"open/high/low/close/volume"}:
        assert name in Bar.__slots__, f"template mentions bar.{name}"
    minute, _, _ = synthetic(days=2, per_day=5)
    keys = set(arrays(bars.aggregate(minute, "1m")))
    for name in set(re.findall(r'a\["(\w+)"\]', CODE)):
        assert name in keys, f'template mentions a["{name}"]'
    for field in ("open", "high", "low", "close", "volume"):
        assert field in Bar.__slots__


def test_online_portfolio_template_parses_and_trades():
    from datetime import date
    from pathlib import Path

    import numpy as np
    import polars as pl

    from btest.calendar import nyse_sessions
    from btest.config import ROOT
    from btest.portfolio import Market, PortfolioConfig, PortfolioEngine
    from btest.runner import load_strategy_class

    path = ROOT / "strategies" / "templates" / "online_portfolio.py"
    info = lab.inspect_code(Path(path).read_text())
    assert info.error is None and info.class_name == "MyOnlinePortfolio" and info.has_decide
    cls = load_strategy_class(path)
    sessions = nyse_sessions(date(2023, 1, 3), date(2023, 6, 30))
    dates = sessions["date"].to_list()
    rng = np.random.default_rng(1)
    frames = {}
    for s in cls.universe:
        close = 100 * np.cumprod(np.exp(rng.normal(0, 0.01, len(dates))))
        frames[s] = pl.DataFrame({
            "date": dates, **{c: close for c in ("open", "high", "low", "close", "raw_close",
                                                 "fill", "cut_open", "cut_high", "cut_low",
                                                 "cut_close", "raw_cut_close")},
            "volume": np.full(len(dates), 1e6), "cut_volume": np.full(len(dates), 5e5)})
    res = PortfolioEngine(Market(dates, frames), sessions, PortfolioConfig()).run(
        cls(), dates[0], dates[-1])
    assert len(res.fills) > 0
