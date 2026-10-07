"""Weekly-bars CWMR with the week ending on each of the 5 possible sessions, 1999-2024 on btest
long history (ETF-only day bars). The calendar version (lab olps/cwmr_weekly_bars) ends each
ISO week; the offset versions use blocks of 5 sessions, so holidays shift them slightly. Each
runs once over the whole window and is reported for 1999-2015, 2016-2024 and in total."""
from datetime import date
from pathlib import Path

import polars as pl
import psycopg

from btest import config, db, longhist, metrics, olps
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import load_strategy_class

START, SPLIT, END = date(1999, 1, 1), date(2016, 1, 1), date(2025, 1, 1)
WEEKLY = load_strategy_class(Path("strategies/olps/cwmr_weekly_bars.py"))

s = config.load(need_alpaca=False)
with psycopg.connect(s.database_url) as conn:
    frames = longhist.frames(conn, WEEKLY.universe, END)
    rates = db.get_rates(conn, "DTB3")
sessions = nyse_sessions(longhist.START, date(END.year + 2, 1, 1))
market = Market(sessions.filter(pl.col("date") < END)["date"].to_list(), frames)
cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.7), data="longhist")


class Offset(WEEKLY):
    """Bars of 5 sessions ending today, trading every 5th session from offset."""
    rebalance = "daily"
    offset = 0

    def _closes(self, data):
        frame = data.frame("close")
        last = frame.height - 1
        return frame[list(range(last % 5, last + 1, 5))].select(self.universe).to_numpy().astype(float)

    def decide(self, as_of, data):
        if (len(data.history("SPY")) - self.offset) % 5:
            return None
        return self.run_online(data)


def run(strategy):
    r = PortfolioEngine(market, sessions, cfg, rates=rates).run(strategy, START, END)
    return r.equity, metrics.trade_stats(r.fills, r.equity)["turnover"]


def part(eq, lo, hi):
    p = eq.filter((pl.col("date") >= lo) & (pl.col("date") < hi))
    before = eq.filter(pl.col("date") < lo)
    if before.height:
        p = pl.concat([before.tail(1), p])
    return metrics.compute(p.select("date", "equity"), rates)


def row(name, eq, turnover):
    cells = []
    for lo, hi in ((START, SPLIT), (SPLIT, END), (START, END)):
        m = part(eq, lo, hi)
        cells.append(f"{m['cagr']:6.1%} {m['sharpe']:5.2f}")
    print(f"{name:26}" + "".join(f"{c:>16}" for c in cells) + f"{turnover:9.0f}x", flush=True)


print(f"{'0.7 bp, CAGR and Sharpe':26}{'1999-2015':>16}{'2016-2024':>16}{'1999-2024':>16}"
      f"{'turnover':>10}")
row("Calendar weeks (ISO)", *run(WEEKLY()))
for k in range(5):
    Offset.offset = k
    row(f"5-session blocks, offset {k}", *run(Offset()))
row("Equal weight, monthly", *run(load_strategy_class(Path("strategies/olps/crp.py"))()))
row("SPY", *run(load_strategy_class(Path("strategies/baseline/buy_hold.py"))()))
