"""Portfolio backtests for strategies with a decide(as_of, data) method.

One decision per scheduled session, at the live timing in btest.daily: the strategy sees data
through the cutoff and returns target weights (and, for options, target contracts). Orders fill
at the fill bar's open, sells before buys, without leverage: a cash account cannot spend more
than its cash, and short puts must be fully cash-secured.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import polars as pl

from btest.calendar import EXCHANGE_TZ
from btest.daily import Timing
from btest.engine import SEC_FEE_RATE, Fill
from btest.sources.base import Dividend, Split

SCHEDULES = ("daily", "weekly", "month_end", "month_start")
FIELDS = ("open", "high", "low", "close", "volume")
OPTION_MULTIPLIER = 100


@dataclass(frozen=True)
class PortfolioCosts:
    slippage_bps: float = 1.0
    sec_fee_rate: float = SEC_FEE_RATE
    # Option fills cross half the spread: this fraction of the price, at least min_tick.
    option_half_spread: float = 0.05
    option_min_half_spread: float = 0.01
    option_fee_per_contract: float = 0.0


@dataclass(frozen=True)
class PortfolioConfig:
    cash: float = 20_000.0
    costs: PortfolioCosts = field(default_factory=PortfolioCosts)
    fractional: bool = True
    # Credit idle cash at the 3-month T-bill rate. Off means cash earns nothing.
    cash_yield: bool = True
    # Smallest order sent, in dollars; Alpaca's minimum notional order is $1.
    min_trade: float = 1.0
    benchmark: str = "SPY"
    timing: Timing = field(default_factory=Timing)
    # "btest" (Alpaca bars from history_start) or "longhist" (btest.longhist, from 1995).
    data: str = "btest"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Targets:
    """What decide() may return instead of a plain {symbol: weight} dict. Weights are shares of
    equity; options maps an option symbol to a contract count, negative for written options.
    Symbols or options left out are closed."""
    weights: dict[str, float] = field(default_factory=dict)
    options: dict[str, int] = field(default_factory=dict)


def is_decision_day(dates: list[date], i: int, schedule: str) -> bool:
    if schedule == "daily":
        return True
    d = dates[i]
    nxt = dates[i + 1] if i + 1 < len(dates) else None
    prev = dates[i - 1] if i > 0 else None
    if schedule == "month_end":
        return nxt is None or nxt.month != d.month
    if schedule == "month_start":
        return prev is None or prev.month != d.month
    if schedule == "weekly":
        return nxt is None or nxt.isocalendar()[1] != d.isocalendar()[1]
    raise ValueError(f"rebalance must be one of {', '.join(SCHEDULES)}")


@dataclass
class Position:
    qty: float = 0.0
    avg_cost: float = 0.0

    def trade(self, qty: float, price: float, mult: float = 1.0) -> float | None:
        """Apply a fill; returns realized P&L when it reduces the position."""
        pos = self.qty
        realized = None
        if pos == 0 or (pos > 0) == (qty > 0):
            self.avg_cost = (self.avg_cost * abs(pos) + price * abs(qty)) / abs(pos + qty)
        else:
            closed = min(abs(qty), abs(pos))
            realized = closed * (price - self.avg_cost) * mult * (1 if pos > 0 else -1)
            if abs(qty) > abs(pos):
                self.avg_cost = price
        self.qty = pos + qty
        if abs(self.qty) < 1e-9:
            self.qty, self.avg_cost = 0.0, 0.0
        return realized


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying: str
    expiry: date
    right: str
    strike: float


def occ_symbol(underlying: str, expiry: date, right: str, strike: float) -> str:
    return f"{underlying}{expiry:%y%m%d}{right}{round(strike * 1000):08d}"


def is_option(symbol: str) -> bool:
    """OCC option symbols end in 15 characters (yymmdd, P or C, strike x 1000); tickers are
    shorter."""
    return len(symbol) > 15


def option_multiplier(symbol: str) -> int:
    return OPTION_MULTIPLIER if is_option(symbol) else 1


def parse_occ(symbol: str) -> OptionContract:
    root, rest = symbol[:-15], symbol[-15:]
    return OptionContract(symbol, root, datetime.strptime(rest[:6], "%y%m%d").date(), rest[6],
                          int(rest[7:]) / 1000)


class Market:
    """Daily rows for every symbol on one session index, as dense arrays. Row i holds the full
    day for past sessions; the cut_* arrays hold what was known at that day's cutoff."""

    def __init__(self, dates: list[date], frames: dict[str, pl.DataFrame]):
        self.dates = dates
        self.symbols = list(frames)
        idx = pl.DataFrame({"date": dates})
        self.full: dict[str, np.ndarray] = {}
        self.cut: dict[str, np.ndarray] = {}
        self.raw: dict[str, np.ndarray] = {}
        cols = {f: [] for f in FIELDS}
        cuts = {f: [] for f in FIELDS}
        raws = {k: [] for k in ("cut_close", "close", "fill")}
        self.first: dict[str, int] = {}
        for s, df in frames.items():
            j = idx.join(df, on="date", how="left")
            present = j["close"].is_not_null().to_numpy()
            self.first[s] = int(np.argmax(present)) if present.any() else len(dates)
            for f in FIELDS:
                ff = (j[f].fill_null(0.0) if f == "volume" else j[f].forward_fill())
                cols[f].append(ff.to_numpy().astype(float))
                cf = j[f"cut_{f}"]
                # A day with no bar by the cutoff (a halt) shows yesterday's full-day value.
                cf = cf.fill_null(0.0) if f == "volume" else cf.fill_null(j[f].forward_fill()
                                                                         .shift(1))
                cuts[f].append(cf.to_numpy().astype(float))
            raws["cut_close"].append(j["raw_cut_close"].to_numpy().astype(float))
            raws["close"].append(j["raw_close"].forward_fill().to_numpy().astype(float))
            # No fill price means no trade at or after the fill time: the order cannot fill, and
            # falling back to the close would fill at the price the decision saw.
            raws["fill"].append(j["fill"].to_numpy().astype(float))
        for f in FIELDS:
            self.full[f] = np.column_stack(cols[f]) if cols[f] else np.empty((len(dates), 0))
            self.cut[f] = np.column_stack(cuts[f]) if cuts[f] else np.empty((len(dates), 0))
        for k, v in raws.items():
            self.raw[k] = np.column_stack(v) if v else np.empty((len(dates), 0))
        self.col = {s: k for k, s in enumerate(self.symbols)}

    def history(self, symbol: str, i: int, field: str, n: int | None) -> np.ndarray:
        k = self.col[symbol]
        lo = self.first[symbol]
        if i < lo:
            return np.empty(0)
        past = self.full[field][lo:i, k]
        out = np.append(past, self.cut[field][i, k])
        return out if n is None else out[-n:]


class Account:
    def __init__(self, cash: float):
        self.cash = cash
        self.stocks: dict[str, Position] = {}
        self.options: dict[str, Position] = {}

    def qty(self, symbol: str) -> float:
        p = self.stocks.get(symbol)
        return p.qty if p else 0.0

    def contracts(self, symbol: str) -> int:
        p = self.options.get(symbol)
        return int(round(p.qty)) if p else 0

    def collateral(self) -> float:
        """Cash set aside for written puts."""
        total = 0.0
        for sym, p in self.options.items():
            c = parse_occ(sym)
            if p.qty < 0 and c.right == "P":
                total += -p.qty * c.strike * OPTION_MULTIPLIER
        return total


class Data:
    """What decide() sees. Everything is as of the decision cutoff; nothing after it."""

    def __init__(self, engine: "PortfolioEngine", i: int):
        self._e = engine
        self._i = i
        self.today: date = engine.market.dates[i]
        self.as_of: datetime = engine.decide_ts[i]
        self.symbols: list[str] = engine.market.symbols

    def history(self, symbol: str, field: str = "close", n: int | None = None) -> np.ndarray:
        """Daily adjusted values ending with today's value at the cutoff: the 15:14 price on a
        full day with btest bars, the session's close with long history (whose open, high and low
        also equal the close, and whose volume is a placeholder). Empty before the symbol's first
        day of data."""
        if field not in FIELDS:
            raise ValueError(f"field must be one of {', '.join(FIELDS)}")
        if symbol not in self._e.market.col:
            raise KeyError(f"{symbol} is not in this strategy's universe")
        return self._e.market.history(symbol, self._i, field, n)

    def frame(self, field: str = "close", n: int | None = None) -> pl.DataFrame:
        """Wide table: a date column and one column per symbol, null before a symbol's data
        starts. The last row is today at the cutoff."""
        m = self._e.market
        lo = 0 if n is None else max(0, self._i + 1 - n)
        block = np.vstack([m.full[field][lo:self._i], m.cut[field][self._i:self._i + 1]])
        cols = {"date": m.dates[lo:self._i + 1]}
        for s, k in m.col.items():
            v = block[:, k].copy()
            v[: max(0, m.first[s] - lo)] = np.nan
            cols[s] = v
        return pl.DataFrame(cols).fill_nan(None)

    def price(self, symbol: str) -> float | None:
        """Last traded price at the cutoff, unadjusted (what orders are sized with)."""
        v = self._e.price_at_cutoff(symbol, self._i)
        return None if v is None or math.isnan(v) else v

    def position(self, symbol: str) -> float:
        return self._e.account.qty(symbol)

    def positions(self) -> dict[str, float]:
        return {s: p.qty for s, p in self._e.account.stocks.items() if p.qty}

    @property
    def cash(self) -> float:
        return self._e.account.cash

    @property
    def equity(self) -> float:
        return self._e.equity_at_cutoff(self._i)

    def weights(self) -> dict[str, float]:
        eq = self.equity
        out = {}
        for s, q in self.positions().items():
            px = self.price(s)
            if px and eq > 0:
                out[s] = q * px / eq
        return out

    def rate(self) -> float:
        """3-month T-bill yield known yesterday, as a fraction (0.05 = 5%)."""
        return self._e.rate_before(self.today)

    def month_position(self) -> tuple[int, int]:
        """Today's session number counted from the start of the month and from its end, both
        starting at 1. The NYSE calendar is published ahead, so the count from the end is known."""
        dates = self._e.all_sessions
        k = self._e.session_pos[self.today]
        start = k
        while start > 0 and dates[start - 1].month == self.today.month:
            start -= 1
        end = k
        while end + 1 < len(dates) and dates[end + 1].month == self.today.month:
            end += 1
        return k - start + 1, end - k + 1

    def report(self, key: str, value) -> None:
        self._e.notes.append({"date": self.today.isoformat(), key: value})

    def expiries(self, underlying: str) -> list[date]:
        """Option expiry dates after today that have data."""
        return [d for d in self._e.options.expiries(underlying) if d > self.today]

    def option_chain(self, underlying: str, expiry: date, right: str = "P") -> pl.DataFrame:
        """Contracts for one expiry with their last price before the cutoff: columns symbol,
        strike, price, volume (the day's contracts traded by the cutoff)."""
        return self._e.options.chain(underlying, expiry, right, self._e.cutoff_ts[self._i])

    def option_positions(self) -> dict[str, int]:
        return {s: int(round(p.qty)) for s, p in self._e.account.options.items() if p.qty}


@dataclass
class PortfolioResult:
    fills: list[Fill]
    equity: pl.DataFrame
    exposure: float
    bars: int
    notes: list[dict]


class NoOptions:
    def expiries(self, underlying):
        return []

    def chain(self, underlying, expiry, right, cutoff):
        return pl.DataFrame(schema={"symbol": pl.Utf8, "strike": pl.Float64,
                                    "price": pl.Float64, "volume": pl.Float64})

    def reference(self, symbol, cutoff):
        return None

    def fills_at(self, symbol, fill_ts, limit, delta):
        return False

    def mark(self, symbol, d):
        return None


class PortfolioEngine:
    def __init__(self, market: Market, sessions: pl.DataFrame, config: PortfolioConfig,
                 splits: dict[str, list[Split]] | None = None,
                 dividends: dict[str, list[Dividend]] | None = None,
                 rates: pl.DataFrame | None = None, options=None):
        self.market = market
        self.config = config
        t = config.timing
        by_date = {d: (o, c) for d, o, c in sessions.select("date", "open_utc", "close_utc")
                   .iter_rows()}
        self.all_sessions = sessions["date"].to_list()
        self.session_pos = {d: k for k, d in enumerate(self.all_sessions)}
        closes = [by_date[d][1] for d in market.dates]
        self.decide_ts = [c - timedelta(minutes=t.decide_min) for c in closes]
        self.cutoff_ts = [c - timedelta(minutes=t.data_min) for c in closes]
        self.fill_ts = [c - timedelta(minutes=t.fill_min) for c in closes]
        self.close_ts = closes
        # Long history decides on a session's close and fills at the next session's open, so
        # its orders execute at the start of the next session, after that night's corporate
        # actions and cash accrual, and the decision day's equity is marked before trading.
        self.next_open = config.data == "longhist"
        if self.next_open:
            opens = {d: o for d, o, _ in sessions.select("date", "open_utc", "close_utc")
                     .iter_rows()}
            after = {d: self.all_sessions[k + 1]
                     for k, d in enumerate(self.all_sessions[:-1])}
            self.decide_ts = closes
            self.fill_ts = [opens[after[d]] if d in after else None for d in market.dates]
        self.splits = splits or {}
        self.dividends = dividends or {}
        self.options = options or NoOptions()
        self._rates = rates if rates is not None else pl.DataFrame(
            schema={"date": pl.Date, "rate": pl.Float64})
        self._rate_dates = self._rates["date"].to_list()
        self._rate_values = self._rates["rate"].to_list()
        self.account = Account(config.cash)
        self.fills: list[Fill] = []
        self.notes: list[dict] = []

    def rate_before(self, d: date) -> float:
        import bisect
        k = bisect.bisect_left(self._rate_dates, d)
        return self._rate_values[k - 1] / 100 if k > 0 else 0.0

    def price_at_cutoff(self, symbol: str, i: int) -> float | None:
        k = self.market.col.get(symbol)
        if k is None:
            return None
        v = self.market.raw["cut_close"][i, k]
        if math.isnan(v) and i > 0:
            v = self.market.raw["close"][i - 1, k]
        return None if math.isnan(v) else float(v)

    def equity_at_cutoff(self, i: int) -> float:
        eq = self.account.cash
        for s, p in self.account.stocks.items():
            if p.qty:
                eq += p.qty * (self.price_at_cutoff(s, i) or 0.0)
        for s, p in self.account.options.items():
            if p.qty:
                mark = self.options.mark(s, self.cutoff_ts[i])
                if mark is None:
                    # As at the close: an unpriced written put still carries its intrinsic
                    # liability, so sizing does not treat it as free.
                    c = parse_occ(s)
                    under = self.price_at_cutoff(c.underlying, i)
                    mark = _intrinsic(c, under) if under is not None else 0.0
                eq += p.qty * mark * OPTION_MULTIPLIER
        return eq

    def equity_at_close(self, i: int) -> float:
        eq = self.account.cash
        for s, p in self.account.stocks.items():
            if p.qty:
                eq += p.qty * float(self.market.raw["close"][i, self.market.col[s]])
        for s, p in self.account.options.items():
            if p.qty:
                mark = self.options.mark(s, self.close_ts[i])
                if mark is None:
                    c = parse_occ(s)
                    under = self.market.raw["close"][i, self.market.col[c.underlying]]
                    mark = _intrinsic(c, under)
                eq += p.qty * mark * OPTION_MULTIPLIER
        return eq

    def run(self, strategy, start: date, end: date) -> PortfolioResult:
        dates = self.market.dates
        schedule = getattr(strategy, "rebalance", "daily")
        if schedule not in SCHEDULES:
            raise ValueError(f"rebalance must be one of {', '.join(SCHEDULES)}")
        snapshots = []
        invested_days = 0
        prev: date | None = None
        queued: tuple[int, Targets] | None = None
        trading = [i for i, d in enumerate(dates) if start <= d < end]
        for i in trading:
            d = dates[i]
            # Shares delivered at an expiry before today must see today's splits and dividends.
            self._settle_expired(i)
            if prev is not None:
                self._corporate_actions(prev, d)
                self._accrue_cash(prev, d)
            if queued is not None:
                self._rebalance(*queued)
                queued = None
            if is_decision_day(self.all_sessions, self.session_pos[d], schedule):
                targets = strategy.decide(self.decide_ts[i], Data(self, i))
                if targets is not None:
                    if self.next_open:
                        # A decision on the run's last session has no next open and is dropped.
                        queued = (i, _as_targets(targets))
                    else:
                        self._rebalance(i, _as_targets(targets))
            eq = self.equity_at_close(i)
            snapshots.append((d, eq, self.account.cash))
            if any(p.qty for p in self.account.stocks.values()) or any(
                    p.qty for p in self.account.options.values()):
                invested_days += 1
            prev = d
        if prev is not None:
            self._settle_expired(len(dates) - 1, through=prev)
        equity = pl.DataFrame(snapshots, schema={"date": pl.Date, "equity": pl.Float64,
                                                 "cash": pl.Float64}, orient="row")
        n = len(trading)
        return PortfolioResult(self.fills, equity, invested_days / n if n else 0.0, n,
                               self.notes)

    def _corporate_actions(self, prev: date, cur: date) -> None:
        for s, p in self.account.stocks.items():
            if not p.qty:
                continue
            for sp in self.splits.get(s, []):
                if prev < sp.ex_date <= cur:
                    ratio = sp.new_rate / sp.old_rate
                    p.qty *= ratio
                    if not self.config.fractional:
                        # Brokers pay cash in lieu of fractional shares after a split.
                        whole = math.floor(p.qty)
                        post_split = self._last_raw_close(s, prev) / ratio
                        self.account.cash += (p.qty - whole) * post_split
                        p.qty = whole
                    p.avg_cost /= ratio
            for dv in self.dividends.get(s, []):
                # Credited on the ex-date rather than the pay date, as in the event engine.
                if prev < dv.ex_date <= cur:
                    self.account.cash += p.qty * dv.rate

    def _last_raw_close(self, symbol: str, d: date) -> float:
        i = self.market.dates.index(d)
        return float(self.market.raw["close"][i, self.market.col[symbol]])

    def _accrue_cash(self, prev: date, cur: date) -> None:
        if not self.config.cash_yield:
            return
        # Collateral for written puts is still cash in the account and earns the same rate.
        self.account.cash += (max(self.account.cash, 0.0) * self.rate_before(cur)
                              * (cur - prev).days / 365)

    def _settle_expired(self, i: int, through: date | None = None) -> None:
        """Expire options whose expiry is before today (or on `through`, at the end of a run).
        In-the-money written puts are assigned at the strike; others expire worthless."""
        today = self.market.dates[i]
        for sym in list(self.account.options):
            p = self.account.options[sym]
            c = parse_occ(sym)
            due = c.expiry < today or (through is not None and c.expiry <= through)
            if not p.qty or not due:
                continue
            k = self.market.col[c.underlying]
            j = _session_index_on_or_before(self.market.dates, c.expiry)
            under = float(self.market.raw["close"][j, k])
            ts = self.close_ts[j]
            itm = _intrinsic(c, under) >= 0.01
            contracts = p.qty
            realized = p.trade(-contracts, 0.0, OPTION_MULTIPLIER)
            if itm:
                shares = contracts * OPTION_MULTIPLIER
                # A written put (contracts < 0) buys shares at the strike; a written call
                # delivers them. Long contracts are exercised the other way round.
                sign = -1 if c.right == "P" else 1
                qty = sign * shares
                pos = self.account.stocks.setdefault(c.underlying, Position())
                stock_realized = pos.trade(qty, c.strike)
                self.account.cash -= qty * c.strike
                self.fills.append(Fill(ts, c.underlying, qty, c.strike, 0.0, 0.0, 0.0,
                                       stock_realized))
            self.fills.append(Fill(ts, sym, -contracts, 0.0, 0.0, 0.0, 0.0, realized))
            del self.account.options[sym]

    def _rebalance(self, i: int, t: Targets) -> None:
        cfg, costs = self.config, self.config.costs
        slip = costs.slippage_bps / 10_000
        ts = self.fill_ts[i]
        equity = self.equity_at_cutoff(i)
        self._trade_options(i, t.options, ts)
        wanted = {s: w for s, w in t.weights.items() if w}
        unknown = [s for s in wanted if s not in self.market.col]
        if unknown:
            raise KeyError(f"targets name symbols outside the universe: {unknown}")
        held = {s: p.qty for s, p in self.account.stocks.items() if p.qty}
        # A symbol with no trade at or after the fill time today cannot be traded today.
        prices = {s: (self.price_at_cutoff(s, i)
                      if not math.isnan(self.market.raw["fill"][i, self.market.col[s]]) else None)
                  for s in set(wanted) | set(held) if s in self.market.col}
        exits, orders = plan_stock_orders(wanted, held, prices, equity, cfg.min_trade)
        for s in sorted(exits | {s for s, v in orders.items() if v < 0}):
            fill = float(self.market.raw["fill"][i, self.market.col[s]])
            have = self.account.qty(s)
            q = -have if s in exits else max(orders[s] / fill, -have)
            if not cfg.fractional and q != -have:
                q = -math.floor(-q)
            if q == 0:
                continue
            price = fill * (1 - slip)
            fees = abs(q) * price * costs.sec_fee_rate
            self.account.cash += abs(q) * price - fees
            realized = self.account.stocks[s].trade(q, price)
            self.fills.append(Fill(ts, s, q, price, 0.0, fees, abs(q) * fill * slip, realized))
        buys = {s: v for s, v in orders.items() if v > 0}
        spendable = self.account.cash - self.account.collateral()
        need = sum(buys.values()) * (1 + slip)
        scale = min(1.0, max(spendable, 0.0) / need) if need > 0 else 0.0
        for s, dollars in sorted(buys.items()):
            fill = float(self.market.raw["fill"][i, self.market.col[s]])
            price = fill * (1 + slip)
            q = dollars * scale / price
            if not cfg.fractional:
                q = math.floor(q)
            if q <= 0 or q * price < cfg.min_trade:
                continue
            self.account.cash -= q * price
            realized = self.account.stocks.setdefault(s, Position()).trade(q, price)
            self.fills.append(Fill(ts, s, q, price, 0.0, 0.0, q * fill * slip, realized))

    def _trade_options(self, i: int, wanted: dict[str, int], ts: datetime) -> None:
        """Option orders are limit orders at the reference price (the last 30-minute bar that
        ended by the cutoff) less or plus half the spread, like the live order run. One fills
        only if the bar holding the fill time traded through the limit."""
        costs = self.config.costs
        today = self.market.dates[i]
        current = {s: self.account.contracts(s) for s in self.account.options}
        for sym in sorted(set(wanted) | set(current), key=lambda s: wanted.get(s, 0)
                          - current.get(s, 0), reverse=True):
            delta = int(wanted.get(sym, 0)) - current.get(sym, 0)
            if delta == 0:
                continue
            c = parse_occ(sym)
            skip = None
            if c.underlying not in self.market.col:
                skip = f"{sym}: underlying {c.underlying} is not in the universe"
            elif c.expiry < today:
                skip = f"{sym}: expired"
            if skip:
                self.notes.append({"date": today.isoformat(), "skipped": skip})
                continue
            ref = self.options.reference(sym, self.cutoff_ts[i])
            if ref is None:
                self.notes.append({"date": today.isoformat(),
                                   "skipped": f"{sym}: no trade today before the cutoff"})
                continue
            price = option_limit(ref, delta, costs)
            if not self.options.fills_at(sym, self.fill_ts[i], price, delta):
                self.notes.append({"date": today.isoformat(),
                                   "skipped": f"{sym}: limit {price:.2f} not reached"})
                continue
            if delta < 0:
                closing = min(-delta, max(current.get(sym, 0), 0))
                opening = -delta - closing
                if c.right == "P":
                    # A written put needs its full strike value free in cash.
                    free = (self.account.cash - self.account.collateral()
                            + closing * price * OPTION_MULTIPLIER)
                    affordable = max(int(free // (c.strike * OPTION_MULTIPLIER)), 0)
                else:
                    # A written call must be covered by shares already held.
                    covered = self.account.qty(c.underlying) // OPTION_MULTIPLIER
                    written = sum(-p.qty for s2, p in self.account.options.items()
                                  if p.qty < 0 and parse_occ(s2).right == "C"
                                  and parse_occ(s2).underlying == c.underlying)
                    affordable = max(int(covered - written), 0)
                if opening > affordable:
                    delta = -(closing + affordable)
                    if delta == 0:
                        self.notes.append({"date": today.isoformat(),
                                           "skipped": f"{sym}: not enough cash or shares "
                                                      "to cover it"})
                        continue
            if delta > 0 and delta * price * OPTION_MULTIPLIER > self.account.cash:
                delta = int(self.account.cash // (price * OPTION_MULTIPLIER))
                if delta == 0:
                    continue
            fee = abs(delta) * costs.option_fee_per_contract
            self.account.cash -= delta * price * OPTION_MULTIPLIER + fee
            pos = self.account.options.setdefault(sym, Position())
            realized = pos.trade(delta, price, OPTION_MULTIPLIER)
            half = abs(price - ref)
            self.fills.append(Fill(ts, sym, delta, price, fee, 0.0,
                                   abs(delta) * half * OPTION_MULTIPLIER, realized))
            if not pos.qty:
                del self.account.options[sym]


def option_limit(reference: float, delta: int, costs: PortfolioCosts) -> float:
    """Limit price for an option order: half the spread through the reference price."""
    half = max(costs.option_min_half_spread, reference * costs.option_half_spread)
    return round(max(reference - half, 0.01) if delta < 0 else reference + half, 2)


def plan_stock_orders(wanted: dict[str, float], held: dict[str, float],
                      prices: dict[str, float | None], equity: float,
                      min_trade: float) -> tuple[set[str], dict[str, float]]:
    """Orders as dollar amounts, like Alpaca notional orders (shares = dollars / fill price):
    positive buys, negative sells. Symbols dropped from the targets are returned separately
    and sold in full. Symbols with no price at the cutoff are left alone. Backtests and the
    live order run both use this."""
    exits: set[str] = set()
    orders: dict[str, float] = {}
    for s in set(wanted) | set(held):
        px = prices.get(s)
        if px is None:
            continue
        have = held.get(s, 0.0)
        if s not in wanted:
            if have:
                exits.add(s)
            continue
        delta = wanted[s] * equity - have * px
        if abs(delta) >= min_trade:
            orders[s] = delta
    return exits, orders


def decide_once(strategy, market: Market, sessions: pl.DataFrame, config: PortfolioConfig,
                cash: float, stocks: dict[str, float], options_held: dict[str, int],
                rates: pl.DataFrame | None = None, options=None) -> dict:
    """One live decision on the last session in `market`, from a real account's holdings.
    Returns targets plus the cutoff prices and equity the order run sizes with."""
    engine = PortfolioEngine(market, sessions, config, rates=rates, options=options)
    engine.account.cash = cash
    engine.account.stocks = {s: Position(q) for s, q in stocks.items() if q}
    engine.account.options = {s: Position(float(q)) for s, q in options_held.items() if q}
    i = len(market.dates) - 1
    raw = strategy.decide(engine.decide_ts[i], Data(engine, i))
    targets = None if raw is None else _as_targets(raw)
    return {
        "session": market.dates[i].isoformat(),
        "as_of": engine.decide_ts[i].isoformat(),
        "targets": None if targets is None else {"weights": targets.weights,
                                                 "options": targets.options},
        "prices": {s: engine.price_at_cutoff(s, i) for s in market.symbols},
        "equity": engine.equity_at_cutoff(i),
        "notes": engine.notes,
    }


def _as_targets(t) -> Targets:
    if isinstance(t, Targets):
        return t
    if isinstance(t, dict):
        return Targets(weights={str(k): float(v) for k, v in t.items()})
    raise TypeError("decide() must return a dict of weights, a Targets, or None")


def _intrinsic(c: OptionContract, under: float) -> float:
    return max(c.strike - under, 0.0) if c.right == "P" else max(under - c.strike, 0.0)


def _session_index_on_or_before(dates: list[date], d: date) -> int:
    import bisect
    return max(bisect.bisect_right(dates, d) - 1, 0)


def session_close_utc(d: date) -> datetime:
    """16:00 New York on d, for tests that build sessions by hand."""
    from zoneinfo import ZoneInfo
    return datetime.combine(d, time(16, 0), ZoneInfo(EXCHANGE_TZ)).astimezone(UTC)
