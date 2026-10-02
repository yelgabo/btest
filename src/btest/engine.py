import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import numpy as np
import polars as pl

from btest.sources.base import Dividend, Split
from btest.strategy import Bar, Strategy

HISTORY_FIELDS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class Costs:
    slippage_bps: float = 1.0
    commission_per_share: float = 0.0
    # SEC Section 31 fee, charged on sell notional. Set from the current SEC rate when needed.
    sec_fee_rate: float = 0.0


@dataclass(frozen=True)
class Config:
    cash: float = 100_000.0
    costs: Costs = field(default_factory=Costs)
    allow_short: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Fill:
    ts: datetime
    symbol: str
    qty: int
    price: float
    commission: float
    fees: float
    slippage: float
    realized_pnl: float | None


@dataclass
class Result:
    fills: list[Fill]
    equity: pl.DataFrame
    exposure: float
    bars: int


class _Symbol:
    def __init__(self, name: str, df: pl.DataFrame):
        self.name = name
        self.ts = df["ts"].to_list()
        self.date = df["date"].to_list()
        self.cols = {c: df[c].to_numpy() for c in HISTORY_FIELDS}
        self.lists = {c: df[c].to_list() for c in HISTORY_FIELDS + ("raw_open", "raw_close")}
        self.idx = -1
        self.position = 0
        self.avg_cost = 0.0
        self.last_close: float | None = None
        self.last_date: date | None = None
        self.pending: list[int] = []
        self.splits: list[Split] = []
        self.dividends: list[Dividend] = []


class Context:
    def __init__(self, engine: "Engine"):
        self._e = engine

    @property
    def now(self) -> datetime:
        return self._e.now

    @property
    def cash(self) -> float:
        return self._e.cash

    @property
    def equity(self) -> float:
        return self._e.equity()

    def position(self, symbol: str) -> int:
        return self._e.symbols[symbol].position

    def history(self, symbol: str, field: str = "close", n: int | None = None) -> np.ndarray:
        """Adjusted values up to and including the current bar of `symbol`."""
        s = self._e.symbols[symbol]
        end = s.idx + 1
        start = 0 if n is None else max(0, end - n)
        return s.cols[field][start:end]

    def order(self, symbol: str, qty: int) -> None:
        """Market order, filled at the symbol's next bar open."""
        if qty:
            self._e.symbols[symbol].pending.append(int(qty))

    def order_target(self, symbol: str, target: int) -> None:
        s = self._e.symbols[symbol]
        self.order(symbol, int(target) - s.position - sum(s.pending))

    def order_target_percent(self, symbol: str, pct: float) -> None:
        s = self._e.symbols[symbol]
        if s.last_close is None:
            return
        target = math.floor(pct * self._e.equity() / s.last_close)
        self.order_target(symbol, target)


class Engine:
    def __init__(self, data: dict[str, pl.DataFrame], config: Config = Config(),
                 splits: dict[str, list[Split]] | None = None,
                 dividends: dict[str, list[Dividend]] | None = None):
        self.config = config
        self.symbols = {name: _Symbol(name, df) for name, df in data.items()}
        for name, s in self.symbols.items():
            s.splits = sorted((splits or {}).get(name, []), key=lambda x: x.ex_date)
            s.dividends = sorted((dividends or {}).get(name, []), key=lambda x: x.ex_date)
        self.cash = config.cash
        self.now: datetime | None = None
        self.fills: list[Fill] = []
        self._order = _event_order(data)

    def equity(self) -> float:
        return self.cash + sum(s.position * s.last_close for s in self.symbols.values()
                               if s.position and s.last_close is not None)

    def run(self, strategy: Strategy) -> Result:
        ctx = Context(self)
        names = list(self.symbols)
        snapshots = []
        cur_date = None
        in_market = 0
        strategy.on_start(ctx)
        for sym_i, row in self._order:
            s = self.symbols[names[sym_i]]
            d = s.date[row]
            if d != cur_date:
                if cur_date is not None:
                    snapshots.append((cur_date, self.equity(), self.cash))
                cur_date = d
            if d != s.last_date:
                if s.last_date is not None:
                    self._corporate_actions(s, s.last_date, d)
                s.last_date = d
            self.now = s.ts[row]
            if s.pending:
                self._fill(s, s.lists["raw_open"][row])
            s.idx = row
            s.last_close = s.lists["raw_close"][row]
            if any(x.position for x in self.symbols.values()):
                in_market += 1
            L = s.lists
            strategy.on_bar(ctx, Bar(s.name, s.ts[row], d, L["open"][row], L["high"][row],
                                     L["low"][row], L["close"][row], L["volume"][row],
                                     L["raw_open"][row], L["raw_close"][row]))
        strategy.on_end(ctx)
        if cur_date is not None:
            snapshots.append((cur_date, self.equity(), self.cash))
        equity = pl.DataFrame(snapshots, schema={"date": pl.Date, "equity": pl.Float64,
                                                 "cash": pl.Float64}, orient="row")
        n = len(self._order)
        return Result(self.fills, equity, in_market / n if n else 0.0, n)

    def _corporate_actions(self, s: _Symbol, prev: date, cur: date) -> None:
        for sp in s.splits:
            if prev < sp.ex_date <= cur:
                ratio = sp.new_rate / sp.old_rate
                if s.position:
                    s.position = math.floor(s.position * ratio)
                    s.avg_cost /= ratio
                s.pending = [math.floor(q * ratio) for q in s.pending]
                if s.last_close is not None:
                    s.last_close /= ratio
        for dv in s.dividends:
            # Credited on the ex-date rather than the pay date, so cash arrives a few weeks early.
            if prev < dv.ex_date <= cur and s.position:
                self.cash += s.position * dv.rate

    def _fill(self, s: _Symbol, open_price: float) -> None:
        qty = sum(s.pending)
        s.pending = []
        if not self.config.allow_short and s.position + qty < 0:
            qty = -s.position
        if qty == 0:
            return
        c = self.config.costs
        slip = c.slippage_bps / 10_000
        price = open_price * (1 + slip) if qty > 0 else open_price * (1 - slip)
        if qty > 0:
            affordable = math.floor(self.cash / (price + c.commission_per_share))
            qty = min(qty, max(affordable, 0))
            if qty == 0:
                return
        notional = abs(qty) * price
        commission = abs(qty) * c.commission_per_share
        fees = notional * c.sec_fee_rate if qty < 0 else 0.0
        self.cash -= qty * price + commission + fees
        realized = self._update_position(s, qty, price)
        self.fills.append(Fill(self.now, s.name, qty, price, commission, fees,
                               abs(qty) * open_price * slip, realized))

    @staticmethod
    def _update_position(s: _Symbol, qty: int, price: float) -> float | None:
        pos = s.position
        realized = None
        if pos == 0 or (pos > 0) == (qty > 0):
            s.avg_cost = (s.avg_cost * abs(pos) + price * abs(qty)) / abs(pos + qty)
        else:
            closed = min(abs(qty), abs(pos))
            realized = closed * (price - s.avg_cost) * (1 if pos > 0 else -1)
            if abs(qty) > abs(pos):
                s.avg_cost = price
        s.position = pos + qty
        if s.position == 0:
            s.avg_cost = 0.0
        return realized


def _event_order(data: dict[str, pl.DataFrame]) -> list[tuple[int, int]]:
    frames = [
        df.select("ts").with_columns(
            pl.lit(i, pl.Int32).alias("sym"), pl.int_range(pl.len(), dtype=pl.Int64).alias("row"),
        )
        for i, df in enumerate(data.values())
    ]
    if not frames:
        return []
    order = pl.concat(frames).sort("ts", "sym")
    return list(zip(order["sym"].to_list(), order["row"].to_list()))
