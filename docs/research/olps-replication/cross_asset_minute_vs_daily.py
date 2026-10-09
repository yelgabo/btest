"""The five cross-asset strategies of 2026-10-09 over 2016-2024 two ways: on btest minute bars with
the live timing (website runs 97-101: decide at 15:30, fill at 15:45) and on long-history daily
bars with their daily timing, each starting from 2016 with no earlier history, so the two differ
only in data and timing. The daily runs are computed here and not saved."""
from dataclasses import replace
from datetime import date
from pathlib import Path

import polars as pl
import psycopg

from btest import config, db, longhist, metrics
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import benchmark_from_daily, load_strategy_class

START, END = date(2016, 1, 1), date(2025, 1, 1)
STRATS = [("olps/cwmr_weekly_open.py", "longhist_open", 97),
          ("olps/equal_weight_open.py", "longhist_open", 98),
          ("portfolio/gtaa_cross_asset.py", "longhist", 99),
          ("risk/inverse_vol_cross_asset.py", "longhist", 100),
          ("portfolio/equal_weight_cross_asset.py", "longhist", 101)]

s = config.load(need_alpaca=False)
sessions = nyse_sessions(longhist.START, date(2027, 1, 1))
dates = sessions.filter((pl.col("date") >= START) & (pl.col("date") < END))["date"].to_list()
with psycopg.connect(s.database_url) as conn:
    rates = db.get_rates(conn, "DTB3")
    minute = {rid: row for rid, *row in conn.execute(
        "SELECT id, (metrics->>'cagr')::float, (metrics->>'sharpe')::float, "
        "(metrics->>'max_drawdown')::float, config->>'data' FROM runs.run WHERE id = ANY(%s)",
        ([r for *_, r in STRATS],)).fetchall()}
    print(f"{START} to {END}; minute = btest bars, live timing; daily = long history from {START}")
    print(f"{'':38}{'minute CAGR':>12}{'Sharpe':>8}{'max DD':>9}   {'daily CAGR':>11}{'Sharpe':>8}"
          f"{'max DD':>9}")
    for path, data, rid in STRATS:
        cls = load_strategy_class(Path("strategies") / path)
        need = list(dict.fromkeys(cls.universe + ["SPY"]))
        frames = {k: v.filter(pl.col("date") >= START) for k, v in longhist.frames(
            conn, need, END, decide_at="open" if data == "longhist_open" else "close").items()}
        costs = PortfolioCosts(slippage_schedule=tuple(
            (a, b, tuple(syms), bps) for a, b, syms, bps in cls.slippage_schedule))
        cfg = PortfolioConfig(costs=costs, data=data)
        r = PortfolioEngine(Market(dates, {k: frames[k] for k in cls.universe}), sessions, cfg,
                            rates=rates).run(cls(), START, END)
        eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash),
                           on="date")
        st = metrics.compute(eq, rates)
        m = minute[rid]
        assert m[3] == "btest", f"run {rid} is not a minute-data run"
        print(f"{cls.__name__ + f' (run {rid})':38}{m[0]:12.2%}{m[1]:8.2f}{m[2]:9.1%}   "
              f"{st['cagr']:11.2%}{st['sharpe']:8.2f}{st['max_drawdown']:9.1%}")
