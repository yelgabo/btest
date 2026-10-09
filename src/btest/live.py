"""Trading deployed lab strategies on Alpaca, on the same timing as the backtests.

Per session (times for a 16:00 close; half days shift with the close):
  15:30  refresh today's bars, run the strategy's decide() in a sandboxed child, store targets
  15:45  diff targets against the account, sell first, then buy with the cash that came in
         (the backtest fills at the 15:45 bar's open)
  16:15  read fills back, price each order with the backtest fill rule, raise alarms

The worker runs live_loop in a thread. Strategy code only ever runs in the child, which has no
broker keys; this module holds the keys and places the orders.
"""

import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from btest import db
from btest.broker import AlpacaBroker, BrokerError
from btest.ingest import log
from btest.daily import Timing
from btest.portfolio import (OPTION_MULTIPLIER, PortfolioCosts, is_decision_day, is_option,
                             option_limit, parse_occ, plan_stock_orders)

DECIDE_TIMEOUT_S = 240
SELL_WAIT_S = 120
FILL_TOLERANCE_BPS = 25.0


@dataclass
class Deployment:
    id: int
    name: str
    strategy_version_id: int
    params: dict
    capital: float
    mode: str
    enabled: bool
    max_daily_loss: float
    max_order: float
    code: str
    strategy_name: str
    version: int


def deployments(conn: psycopg.Connection, only_enabled: bool = True) -> list[Deployment]:
    rows = conn.execute(
        "SELECT d.id, d.name, d.strategy_version_id, d.params, d.capital, d.mode, d.enabled, "
        "d.max_daily_loss, d.max_order, v.code, s.name, v.version FROM live.deployment d "
        "JOIN lab.strategy_version v ON v.id = d.strategy_version_id "
        "JOIN lab.strategy s ON s.id = v.strategy_id "
        + ("WHERE d.enabled " if only_enabled else "") + "ORDER BY d.id").fetchall()
    return [Deployment(*r) for r in rows]


def event(conn: psycopg.Connection, dep_id: int | None, level: str, message: str) -> None:
    conn.execute("INSERT INTO live.event (deployment_id, level, message) VALUES (%s, %s, %s)",
                 (dep_id, level, message))
    conn.commit()
    log(f"live {level}: {message}")


def session_times(conn: psycopg.Connection, d: date) -> dict | None:
    row = conn.execute("SELECT close_utc FROM market.session WHERE date = %s", (d,)).fetchone()
    if row is None:
        return None
    close = row[0]
    t = Timing()
    return {"close": close, "decide": close - timedelta(minutes=t.decide_min),
            "order": close - timedelta(minutes=t.fill_min),
            "reconcile": close + timedelta(minutes=15)}


def account_state(broker: AlpacaBroker, universe: list[str]) -> dict:
    acct = broker.account()
    stocks, options, value, intraday = {}, {}, 0.0, 0.0
    for p in broker.positions():
        sym = p["symbol"]
        if p.get("asset_class") == "us_option":
            if parse_occ(sym).underlying not in universe:
                continue
            options[sym] = int(float(p["qty"]))
        elif sym in universe:
            stocks[sym] = float(p["qty"])
        else:
            continue
        value += float(p["market_value"])
        intraday += float(p.get("unrealized_intraday_pl") or 0.0)
    collateral = sum(-q * parse_occ(s).strike * OPTION_MULTIPLIER for s, q in options.items()
                     if q < 0 and parse_occ(s).right == "P")
    return {"cash": float(acct["cash"]), "equity": float(acct["equity"]),
            "last_equity": float(acct["last_equity"]), "stocks": stocks, "options": options,
            "positions_value": value, "intraday_pl": intraday, "collateral": collateral}


def capped(account: dict, capital: float) -> dict:
    """The account as the strategy should see it: cash limited so cash plus its positions is
    at most the deployed capital, even when the broker account holds more."""
    cash = max(0.0, min(account["cash"], capital - account["positions_value"]))
    return account | {"cash": cash}


def run_decision(dep: Deployment, account: dict, session: date) -> dict:
    """Run decide() for `session` in a child process with no broker keys."""
    from btest.worker import child_env
    from btest.worker_proc import run_child
    payload = {"kind": "decide", "code": dep.code, "name": dep.strategy_name,
               "version": dep.version, "params": dep.params, "session": session.isoformat(),
               "account": capped(account, dep.capital)}
    result, out = run_child([sys.executable, "-m", "btest.child"], payload, DECIDE_TIMEOUT_S,
                            child_env(), "live decision")
    result["log"] = out
    return result


def strategy_equity(dep: Deployment, account: dict) -> float:
    """Live sizing is capped at the deployed capital and does not compound: after gains the
    strategy still trades `capital`, after losses the smaller account equity. A backtest
    compounds, so the two drift apart once the deployment has gained or lost money."""
    return min(dep.capital, account["equity"])


def place_orders(conn: psycopg.Connection, broker: AlpacaBroker, dep: Deployment,
                 decision_id: int, decision: dict, account: dict) -> tuple[list[dict], list[str]]:
    """Sells first; waits for them; then buys sized to the cash actually available. An order
    the broker rejects is recorded and skipped so the rest still go out; returns the placed
    orders and a description of each rejection."""
    targets = decision["targets"] or {"weights": {}, "options": {}}
    prices = {s: p for s, p in decision["prices"].items() if p is not None}
    equity = strategy_equity(dep, account)
    exits, orders = plan_stock_orders(targets["weights"], account["stocks"], prices, equity,
                                      1.0)
    limit = dep.max_order * dep.capital
    session = decision["session"]
    placed, rejected = [], []

    def cid(symbol: str, leg: str) -> str:
        return f"btest:{dep.id}:{session}:{symbol}:{leg}"

    def send(symbol: str, side: str, leg: str, **kw) -> None:
        if is_option(symbol):
            notional = (kw.get("qty") or 0) * kw["limit_price"] * OPTION_MULTIPLIER
        else:
            notional = kw.get("notional") or (kw.get("qty") or 0) * prices.get(symbol, 0.0)
        if notional > limit:
            event(conn, dep.id, "alarm", f"refused {side} {symbol} ${notional:,.0f}: above the "
                  f"${limit:,.0f} order limit")
            return
        client_id = cid(symbol, leg)
        existing = broker.order_by_client_id(client_id)
        try:
            order = existing or (
                broker.close_position(symbol, client_id) if kw.get("close")
                else broker.submit(symbol, side, client_id, notional=kw.get("notional"),
                                   qty=kw.get("qty"), limit_price=kw.get("limit_price")))
        except BrokerError as e:
            order = {"id": None, "status": "rejected"}
            rejected.append(f"{side} {symbol}: {e}")
            event(conn, dep.id, "alarm", f"order rejected, {side} {symbol}: {e}")
        conn.execute(
            "INSERT INTO live.order (decision_id, client_order_id, broker_id, symbol, side, "
            "notional, qty, limit_price, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (client_order_id) DO UPDATE SET broker_id = EXCLUDED.broker_id, "
            "status = EXCLUDED.status WHERE live.order.status = 'rejected'",
            (decision_id, client_id, order["id"], symbol, side, kw.get("notional"),
             kw.get("qty"), kw.get("limit_price"), order["status"]))
        conn.commit()
        if order["id"] is not None:
            placed.append(order)

    for symbol in sorted(exits):
        send(symbol, "sell", "exit", close=True)
    for symbol, dollars in sorted(orders.items()):
        if dollars < 0:
            send(symbol, "sell", "trim", notional=round(-dollars, 2))
    _trade_options(conn, dep, targets.get("options") or {}, account, list(prices), send,
                   decision.get("cutoff"))
    _wait_filled(broker, [o["id"] for o in placed], SELL_WAIT_S)

    buys = {s: d for s, d in orders.items() if d > 0}
    if buys:
        fresh = account_state(broker, list(prices))
        held_value = sum(q * prices.get(s, 0.0) for s, q in fresh["stocks"].items())
        # Cash backing written puts is spoken for, in the account and within the capital.
        spendable = min(fresh["cash"] - fresh["collateral"],
                        dep.capital - held_value - fresh["collateral"])
        need = sum(buys.values())
        scale = min(1.0, max(spendable, 0.0) / need) if need else 0.0
        for symbol, dollars in sorted(buys.items()):
            amount = round(dollars * scale, 2)
            if amount >= 1.0:
                send(symbol, "buy", "buy", notional=amount)
    return placed, rejected


def _trade_options(conn, dep, wanted: dict[str, int], account: dict, universe: list[str],
                   send, cutoff: datetime | None) -> None:
    """Limit orders priced like the backtest: half the spread through the close of the last
    30-minute bar that ended by the cutoff. Written puts must be backed by free cash within
    the deployed capital; written calls by shares held."""
    costs = PortfolioCosts()
    free = (min(account["cash"], dep.capital - account["positions_value"])
            - account["collateral"])
    for sym in sorted(set(wanted) | set(account["options"])):
        delta = int(wanted.get(sym, 0)) - account["options"].get(sym, 0)
        if delta == 0:
            continue
        c = parse_occ(sym)
        if c.underlying not in universe:
            event(conn, dep.id, "alarm", f"refused {sym}: {c.underlying} is not in the universe")
            continue
        ref = None if cutoff is None else _option_reference_price(conn, sym, cutoff)
        if ref is None:
            event(conn, dep.id, "warn", f"no trade today in {sym} before the cutoff; skipped")
            continue
        opening = max(-delta - max(account["options"].get(sym, 0), 0), 0)
        if opening and c.right == "P":
            need = opening * c.strike * OPTION_MULTIPLIER
            if need > free:
                event(conn, dep.id, "alarm", f"refused {sym}: needs ${need:,.0f} of cash, "
                      f"${free:,.0f} free")
                continue
            free -= need
        if opening and c.right == "C":
            covered = account["stocks"].get(c.underlying, 0.0) // OPTION_MULTIPLIER
            if opening > covered:
                event(conn, dep.id, "alarm", f"refused {sym}: calls not covered by shares")
                continue
        send(sym, "sell" if delta < 0 else "buy", "opt", qty=abs(delta),
             limit_price=option_limit(ref, delta, costs))


def _option_reference_price(conn, symbol: str, cutoff: datetime) -> float | None:
    """Close of today's last 30-minute bar that ended by the cutoff, as in the backtest."""
    row = conn.execute(
        "SELECT close FROM market.option_bar_30m WHERE symbol = %s "
        "AND ts + interval '30 minutes' <= %s AND ts >= %s ORDER BY ts DESC LIMIT 1",
        (symbol, cutoff + timedelta(minutes=1),
         cutoff.replace(hour=0, minute=0, second=0, microsecond=0))).fetchone()
    return row[0] if row else None


def _wait_filled(broker: AlpacaBroker, ids: list[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    pending = set(ids)
    while pending and time.monotonic() < deadline:
        for oid in list(pending):
            o = broker._call("GET", f"/v2/orders/{oid}")
            if o["status"] in ("filled", "canceled", "expired", "rejected"):
                pending.discard(oid)
        if pending:
            time.sleep(5)


def kill_switch(conn, dep: Deployment, account: dict) -> bool:
    """True when trading must stop: the deployment's positions lost more than max_daily_loss
    of its capital since the last close. Disables the deployment so it stays stopped until
    someone re-enables it."""
    change = account.get("intraday_pl", 0.0) / dep.capital
    if change < -dep.max_daily_loss:
        conn.execute("UPDATE live.deployment SET enabled = false, updated_at = now() "
                     "WHERE id = %s", (dep.id,))
        conn.commit()
        event(conn, dep.id, "alarm", f"kill switch: positions down {change:.1%} of capital "
              "today; deployment disabled")
        return True
    return False


def reconcile(conn: psycopg.Connection, broker: AlpacaBroker, dep: Deployment,
              decision_id: int, data_dir, session: date) -> None:
    """Record fills and compare each with the backtest's price for it: the open of the 15:45
    minute bar plus slippage."""
    from btest import daily, loader
    rows = conn.execute("SELECT id, client_order_id, symbol, side FROM live.order "
                        "WHERE decision_id = %s", (decision_id,)).fetchall()
    times = session_times(conn, session)
    for oid, client_id, symbol, side in rows:
        o = broker.order_by_client_id(client_id)
        if o is None:
            continue
        filled = float(o.get("filled_qty") or 0)
        avg = float(o["filled_avg_price"]) if o.get("filled_avg_price") else None
        model = None
        if len(symbol) <= 15 and times is not None:
            fill_ts = times["close"] - timedelta(minutes=daily.Timing().fill_min)
            bars = loader.read_raw(data_dir, symbol, fill_ts, times["close"], "ts, open")
            if not bars.is_empty():
                slip = PortfolioCosts().slippage_bps / 10_000
                model = bars["open"][0] * (1 + slip if side == "buy" else 1 - slip)
        conn.execute(
            "UPDATE live.order SET status = %s, filled_qty = %s, filled_avg_price = %s, "
            "filled_at = %s, model_price = %s WHERE id = %s",
            (o["status"], filled, avg, o.get("filled_at"), model, oid))
        if avg and model:
            gap = (avg / model - 1) * 10_000 * (1 if side == "buy" else -1)
            if gap > FILL_TOLERANCE_BPS:
                event(conn, dep.id, "warn", f"{side} {symbol} filled {gap:.0f} bps worse than "
                      f"the backtest assumes ({avg:.4f} vs {model:.4f})")
    after = (datetime.combine(session, datetime.min.time(), UTC) - timedelta(days=1)).isoformat()
    for a in broker.activities("OPASN,OPEXP,OPXRC", after):
        event(conn, dep.id, "info", f"option {a.get('activity_type')}: {a.get('symbol')} "
              f"qty {a.get('qty')}")
    conn.execute("UPDATE live.decision SET status = 'reconciled' WHERE id = %s", (decision_id,))
    conn.commit()


def step(conn: psycopg.Connection, broker: AlpacaBroker, dep: Deployment, settings,
         now: datetime, refresh) -> None:
    """Advance one deployment through today's schedule. Safe to call repeatedly: each stage
    runs once, keyed by the decision row."""
    from zoneinfo import ZoneInfo

    from btest.calendar import EXCHANGE_TZ
    session = now.astimezone(ZoneInfo(EXCHANGE_TZ)).date()
    times = session_times(conn, session)
    if times is None:
        return
    sessions = db.get_sessions(conn, session - timedelta(days=40), session + timedelta(days=40))
    dates = sessions["date"].to_list()
    rebalance = _rebalance_of(dep.code)
    if session not in dates or not is_decision_day(dates, dates.index(session), rebalance):
        return
    row = conn.execute("SELECT id, status, targets, prices, account FROM live.decision "
                       "WHERE deployment_id = %s AND session = %s",
                       (dep.id, session)).fetchone()
    if row is None and times["decide"] <= now < times["order"]:
        universe = _universe_of(dep.code)
        refresh(universe, "option_chain" in dep.code)
        account = account_state(broker, universe)
        result = run_decision(dep, account, session)
        status = "failed" if result.get("error") else (
            "no_change" if result.get("targets") is None else "decided")
        conn.execute(
            "INSERT INTO live.decision (deployment_id, session, as_of, status, targets, prices, "
            "account, error, log) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (dep.id, session, times["decide"], status, Jsonb(result.get("targets")),
             Jsonb(result.get("prices")), Jsonb(account), result.get("error"),
             (result.get("log") or "")[-6000:]))
        conn.commit()
        if status == "failed":
            event(conn, dep.id, "alarm", f"decision failed: {result['error']}")
        return
    if row is None:
        if now >= times["order"]:
            # The row also stops this warning repeating on every poll for the rest of the day.
            msg = "no decision before the order time; session missed"
            conn.execute(
                "INSERT INTO live.decision (deployment_id, session, as_of, status, error) "
                "VALUES (%s, %s, %s, 'failed', %s)", (dep.id, session, times["decide"], msg))
            conn.commit()
            event(conn, dep.id, "warn", f"{session}: {msg}")
        return
    decision_id, status, targets, prices, account = row
    if status == "decided" and times["order"] <= now < times["close"]:
        fresh = account_state(broker, list(prices))
        if kill_switch(conn, dep, fresh):
            conn.execute("UPDATE live.decision SET status = 'halted' WHERE id = %s",
                         (decision_id,))
            conn.commit()
            return
        try:
            _, rejected = place_orders(
                conn, broker, dep, decision_id,
                {"targets": targets, "prices": prices, "session": session.isoformat(),
                 "cutoff": times["close"] - timedelta(minutes=Timing().data_min)}, fresh)
            # 'ordered' rather than 'failed' so the orders that did go out still reconcile;
            # the error column carries the partial failure.
            conn.execute("UPDATE live.decision SET status = 'ordered', error = %s WHERE id = %s",
                         ("rejected: " + "; ".join(rejected) if rejected else None,
                          decision_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            event(conn, dep.id, "alarm", f"order run failed: {e}")
            conn.execute("UPDATE live.decision SET status = 'failed', error = %s WHERE id = %s",
                         (str(e), decision_id))
            conn.commit()
    elif status == "ordered" and now >= times["reconcile"]:
        # The 15:30 refresh ended before the 15:45 bar the fills are compared against.
        refresh(_universe_of(dep.code), False)
        reconcile(conn, broker, dep, decision_id, settings.data_dir, session)


def _universe_of(code: str) -> list[str]:
    from btest.lab import inspect_code
    return inspect_code(code).universe or []


def _rebalance_of(code: str) -> str:
    from btest.lab import inspect_code
    return inspect_code(code).rebalance


def live_loop(settings, stop, poll_s: float = 30.0) -> None:
    """Worker thread. Needs Alpaca keys; uses the paper endpoint unless BTEST_LIVE_MODE=live."""
    from btest.ingest import ingest
    from btest.sources.alpaca import AlpacaSource
    mode = os.environ.get("BTEST_LIVE_MODE", "paper")
    broker = AlpacaBroker(settings.alpaca_key, settings.alpaca_secret, paper=mode != "live")
    source = AlpacaSource(settings.alpaca_key, settings.alpaca_secret)

    def refresh(universe: list[str], options: bool) -> None:
        """Bring today's bars (and, for option strategies, the next expiries) up to now."""
        from btest import loader
        from btest.options import ingest_options
        with psycopg.connect(settings.database_url) as c:
            ingest(c, source, settings.data_dir, universe, settings.history_start)
            if options:
                today = datetime.now(UTC).date()
                for u in universe:
                    ingest_options(c, source, u, today, today + timedelta(days=75),
                                   loader.daily_closes(settings.data_dir, u))

    log(f"live loop ready ({mode})")
    while not stop.is_set():
        try:
            with psycopg.connect(settings.database_url) as conn:
                for dep in deployments(conn):
                    if dep.mode != mode:
                        continue
                    step(conn, broker, dep, settings, datetime.now(UTC), refresh)
        except Exception as e:
            log(f"live loop error: {type(e).__name__}: {e}")
        stop.wait(poll_s)


def _check_overlap(conn, dep_id: int | None, code: str, mode: str) -> None:
    """Positions are attributed to a deployment by symbol, so two enabled deployments on one
    account that share a symbol would trade, close and kill-switch on each other's shares."""
    universe = set(_universe_of(code))
    for d in deployments(conn):
        if d.mode != mode or d.id == dep_id:
            continue
        shared = universe & set(_universe_of(d.code))
        if shared:
            raise SystemExit(f"universe overlaps enabled {mode} deployment {d.name} on "
                             f"{', '.join(sorted(shared))}; disable it first")


def enable(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT d.id, d.mode, v.code FROM live.deployment d "
        "JOIN lab.strategy_version v ON v.id = d.strategy_version_id WHERE d.name = %s",
        (name,)).fetchone()
    if row is None:
        return False
    _check_overlap(conn, row[0], row[2], row[1])
    conn.execute("UPDATE live.deployment SET enabled = true, updated_at = now() WHERE id = %s",
                 (row[0],))
    conn.commit()
    return True


def deploy(conn, name: str, strategy: str, version: int | None, capital: float,
           params: dict, mode: str = "paper") -> int:
    row = conn.execute(
        "SELECT v.id, v.code FROM lab.strategy s "
        "JOIN lab.strategy_version v ON v.strategy_id = s.id "
        "WHERE s.name = %s AND NOT s.archived AND s.kind = 'strategy' "
        + ("AND v.version = %s " if version else "") + "ORDER BY v.version DESC LIMIT 1",
        (strategy, version) if version else (strategy,)).fetchone()
    if row is None:
        raise SystemExit(f"no lab strategy {strategy}" + (f" v{version}" if version else ""))
    _check_overlap(conn, None, row[1], mode)
    dep_id = conn.execute(
        "INSERT INTO live.deployment (name, strategy_version_id, params, capital, mode) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (name, row[0], Jsonb(params), capital, mode)).fetchone()[0]
    conn.commit()
    return dep_id
