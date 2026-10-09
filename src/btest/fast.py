"""Single-symbol fast path. A strategy's signals() returns a target portfolio weight per bar;
the kernel replays the event engine's fill rules (next-bar open, whole shares, cash cap,
slippage, fees, splits, dividends) in compiled code."""

import math
from dataclasses import dataclass

import numba
import numpy as np
import polars as pl

from btest.engine import HISTORY_FIELDS, Config
from btest.sources.base import Dividend, Split


@dataclass
class FastResult:
    fill_bar: np.ndarray
    fill_qty: np.ndarray
    fill_price: np.ndarray
    fill_realized: np.ndarray
    equity: pl.DataFrame
    exposure: float
    costs: float


def arrays(bars: pl.DataFrame) -> dict[str, np.ndarray]:
    out = {c: bars[c].to_numpy() for c in HISTORY_FIELDS + ("raw_open", "raw_close")}
    out["ts"] = bars["ts"].to_numpy()
    out["date"] = bars["date"].to_numpy()
    return out


def corporate_action_arrays(dates: np.ndarray, splits: list[Split],
                            dividends: list[Dividend]) -> tuple[np.ndarray, np.ndarray]:
    """Per-bar split ratio and dividend per share, placed on the first bar dated on or after
    the ex-date. The first bar of the window gets nothing, matching the event engine."""
    n = len(dates)
    ratio = np.ones(n)
    div = np.zeros(n)
    for items, apply in ((splits, "split"), (dividends, "div")):
        for x in items:
            i = int(np.searchsorted(dates, np.datetime64(x.ex_date), side="left"))
            if i == 0 or i >= n:
                continue
            if apply == "split":
                ratio[i] *= x.new_rate / x.old_rate
            else:
                div[i] += x.rate
    return ratio, div


@numba.njit(cache=True)
def _kernel(weights, raw_open, raw_close, day_end, split_ratio, div_rate, cash0, slip,
            commission, sec_fee, allow_short):
    n = len(raw_open)
    cash = cash0
    pos = 0
    avg_cost = 0.0
    pending = 0
    cur_w = 0.0
    in_market = 0
    costs = 0.0
    fill_bar = np.empty(n, np.int64)
    fill_qty = np.empty(n, np.int64)
    fill_price = np.empty(n)
    fill_real = np.empty(n)
    nf = 0
    day_equity = np.empty(n)
    day_cash = np.empty(n)
    nd = 0
    for i in range(n):
        if split_ratio[i] != 1.0:
            if pos != 0:
                pos = int(pos * split_ratio[i])
                avg_cost /= split_ratio[i]
            pending = int(pending * split_ratio[i])
        if div_rate[i] != 0.0 and pos != 0:
            cash += pos * div_rate[i]
        if pending != 0:
            qty = pending
            pending = 0
            if not allow_short and pos + qty < 0:
                qty = -pos
            if qty != 0:
                o = raw_open[i]
                price = o * (1 + slip) if qty > 0 else o * (1 - slip)
                if qty > 0:
                    affordable = math.floor(cash / (price + commission))
                    if affordable < 0:
                        affordable = 0
                    if affordable < qty:
                        qty = affordable
                if qty != 0:
                    notional = abs(qty) * price
                    comm = abs(qty) * commission
                    fees = notional * sec_fee if qty < 0 else 0.0
                    cash -= qty * price + comm + fees
                    costs += comm + fees + abs(qty) * o * slip
                    realized = np.nan
                    if pos == 0 or (pos > 0) == (qty > 0):
                        avg_cost = (avg_cost * abs(pos) + price * abs(qty)) / abs(pos + qty)
                    else:
                        closed = min(abs(qty), abs(pos))
                        sign = 1.0 if pos > 0 else -1.0
                        realized = closed * (price - avg_cost) * sign
                        if abs(qty) > abs(pos):
                            avg_cost = price
                    pos += qty
                    if pos == 0:
                        avg_cost = 0.0
                    fill_bar[nf] = i
                    fill_qty[nf] = qty
                    fill_price[nf] = price
                    fill_real[nf] = realized
                    nf += 1
        if pos != 0:
            in_market += 1
        w = weights[i]
        if not np.isnan(w) and w != cur_w:
            equity = cash + pos * raw_close[i]
            target = math.floor(w * equity / raw_close[i])
            pending = target - pos
            cur_w = w
        if day_end[i]:
            day_equity[nd] = cash + pos * raw_close[i]
            day_cash[nd] = cash
            nd += 1
    return (fill_bar[:nf], fill_qty[:nf], fill_price[:nf], fill_real[:nf], day_equity[:nd],
            day_cash[:nd], in_market, costs)


class Prepared:
    """Arrays shared by every run over the same bars, so sweeps pay for them once."""

    def __init__(self, bars: pl.DataFrame, splits: list[Split], dividends: list[Dividend]):
        self.arrays = arrays(bars)
        dates = self.arrays["date"]
        self.day_end = np.append(dates[1:] != dates[:-1], True)
        self.days = dates[self.day_end]
        self.split_ratio, self.div_rate = corporate_action_arrays(dates, splits, dividends)


def run_fast(prep: Prepared, weights: np.ndarray, config: Config) -> FastResult:
    a = prep.arrays
    if len(weights) != len(a["raw_open"]):
        raise ValueError(f"signals returned {len(weights)} weights for {len(a['raw_open'])} bars")
    c = config.costs
    fb, fq, fp, fr, eq, cash, in_market, costs = _kernel(
        np.asarray(weights, dtype=np.float64), a["raw_open"], a["raw_close"], prep.day_end,
        prep.split_ratio, prep.div_rate, config.cash, c.slippage_bps / 10_000,
        c.commission_per_share, c.sec_fee_rate, config.allow_short,
    )
    equity = pl.DataFrame({"date": prep.days, "equity": eq, "cash": cash})
    n = len(weights)
    return FastResult(fb, fq, fp, fr, equity, in_market / n if n else 0.0, costs)
