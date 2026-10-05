import subprocess
from datetime import date

import psycopg
import pytest

from btest import db, lab, live
from btest.config import Settings

TEST_DB = "postgresql://localhost:5432/btest_test_live"
SETTINGS = Settings("", "", "", None, ["SPY", "AGG", "BIL", "EFA"], date(2016, 1, 1),
                    date(2025, 1, 1))

CODE = '''from btest.strategy import Strategy


class Rotate(Strategy):
    universe = ["A", "B"]
    rebalance = "month_end"
    params = {}

    def decide(self, as_of, data):
        return {"B": 0.5}
'''


class FakeBroker:
    def __init__(self, cash, positions, equity=None, last_equity=None):
        self.cash = cash
        self.pos = positions
        self.equity = equity if equity is not None else cash + sum(
            q * px for q, px in positions.values())
        self.last_equity = last_equity or self.equity
        self.orders: dict[str, dict] = {}
        self.calls: list[tuple] = []

    def account(self):
        return {"cash": str(self.cash), "equity": str(self.equity),
                "last_equity": str(self.last_equity)}

    def positions(self):
        return [{"symbol": s, "qty": str(q), "market_value": str(q * px),
                 "asset_class": "us_equity"} for s, (q, px) in self.pos.items()]

    def submit(self, symbol, side, client_order_id, notional=None, qty=None, limit_price=None):
        self.calls.append((side, symbol, notional, qty))
        o = {"id": f"o{len(self.orders)}", "status": "filled", "client_order_id": client_order_id}
        self.orders[client_order_id] = o
        if side == "sell" and qty is not None:
            q, px = self.pos.pop(symbol)
            self.cash += q * px
        elif side == "buy":
            self.cash -= notional
        return o

    def close_position(self, symbol, client_order_id):
        return self.submit(symbol, "sell", client_order_id, qty=self.pos[symbol][0])

    def order_by_client_id(self, client_order_id):
        return self.orders.get(client_order_id)

    def _call(self, method, path, **kw):
        return {"status": "filled"}


@pytest.fixture(scope="module")
def testdb():
    try:
        subprocess.run(["dropdb", "--if-exists", "btest_test_live"], check=True,
                       capture_output=True)
        subprocess.run(["createdb", "btest_test_live"], check=True, capture_output=True)
        conn = psycopg.connect(TEST_DB)
    except (OSError, subprocess.CalledProcessError, psycopg.OperationalError):
        pytest.skip("local Postgres not available")
    db.migrate(conn)
    lab.create(conn, "portfolio/rotate", CODE)
    yield conn
    conn.close()


def deployment(conn, name, **kw):
    dep_id = live.deploy(conn, name, "portfolio/rotate", None, kw.pop("capital", 20_000.0), {})
    if kw:
        sets = ", ".join(f"{k} = %s" for k in kw)
        conn.execute(f"UPDATE live.deployment SET {sets} WHERE id = %s", (*kw.values(), dep_id))
        conn.commit()
    [dep] = [d for d in live.deployments(conn, only_enabled=False) if d.id == dep_id]
    return dep


def decision_row(conn, dep):
    return conn.execute(
        "INSERT INTO live.decision (deployment_id, session, as_of, status) VALUES "
        "(%s, '2026-10-30', now(), 'decided') RETURNING id", (dep.id,)).fetchone()[0]


def test_inspect_reads_portfolio_settings():
    info = lab.inspect_code(CODE)
    assert (info.has_decide, info.universe, info.rebalance) == (True, ["A", "B"], "month_end")
    bad = lab.inspect_code(CODE.replace('    universe = ["A", "B"]\n', ""))
    assert "universe" in bad.error


def test_runs_of_decide_strategies_use_their_universe():
    spec = {"start": "2016-01-01", "end": "2024-12-31", "config": {"fractional": False,
                                                                    "benchmark": "60/40",
                                                                    "allow_short": True}}
    out = lab.validate_spec("run", spec, SETTINGS, False, ["SPY", "AGG"])
    assert out["symbols"] == ["SPY", "AGG"]
    assert out["config"] == {"fractional": False, "benchmark": "60/40"}
    with pytest.raises(ValueError, match="fast path"):
        lab.validate_spec("sweep", spec, SETTINGS, False, ["SPY"])


def test_strategy_sees_cash_capped_at_capital():
    acct = {"cash": 100_000.0, "positions_value": 5_000.0, "stocks": {}, "options": {}}
    assert live.capped(acct, 20_000.0)["cash"] == 15_000.0


def test_order_run_sells_first_then_buys_and_is_idempotent(testdb):
    dep = deployment(testdb, "rotate")
    broker = FakeBroker(19_000.0, {"A": (100.0, 10.0)})
    account = live.account_state(broker, ["A", "B"])
    decision = {"targets": {"weights": {"B": 0.5}, "options": {}},
                "prices": {"A": 10.0, "B": 50.0}, "session": "2026-10-30"}
    did = decision_row(testdb, dep)
    live.place_orders(testdb, broker, dep, did, decision, account)
    assert broker.calls == [("sell", "A", None, 100.0), ("buy", "B", 10_000.0, None)]
    live.place_orders(testdb, broker, dep, did, decision, account)
    assert len(broker.calls) == 2
    ids = [r[0] for r in testdb.execute("SELECT client_order_id FROM live.order ORDER BY id")]
    assert ids == [f"btest:{dep.id}:2026-10-30:A:exit", f"btest:{dep.id}:2026-10-30:B:buy"]


def test_order_limit_refuses_oversized_orders(testdb):
    dep = deployment(testdb, "capped", max_order=0.25)
    broker = FakeBroker(20_000.0, {})
    did = testdb.execute(
        "INSERT INTO live.decision (deployment_id, session, as_of, status) VALUES "
        "(%s, '2026-10-29', now(), 'decided') RETURNING id", (dep.id,)).fetchone()[0]
    live.place_orders(testdb, broker, dep, did,
                      {"targets": {"weights": {"B": 1.0}}, "prices": {"B": 50.0},
                       "session": "2026-10-29"}, live.account_state(broker, ["B"]))
    assert broker.calls == []
    msg = testdb.execute("SELECT message FROM live.event WHERE deployment_id = %s",
                         (dep.id,)).fetchone()[0]
    assert "order limit" in msg


def test_kill_switch_measures_the_deployment_not_the_whole_account(testdb):
    dep = deployment(testdb, "kill", enabled=False)
    # $1,200 down on $20,000 of capital is 6%, even though a $100k account is down only 1.2%.
    assert live.kill_switch(testdb, dep, {"intraday_pl": -1_200.0})
    assert not live.kill_switch(testdb, dep, {"intraday_pl": -500.0})


def test_written_puts_must_fit_in_free_cash_within_capital(testdb):
    dep = deployment(testdb, "puts", capital=20_000.0)
    broker = FakeBroker(100_000.0, {})
    account = live.account_state(broker, ["XLF"])
    sent = []
    live._trade_options(testdb, dep, {"XLF240315P00045000": -5}, account, ["XLF"],
                        lambda *a, **kw: sent.append((a, kw)), None)
    assert sent == []  # no reference price without a cutoff: skipped, not guessed
    testdb.execute("INSERT INTO market.option_contract VALUES "
                   "('XLF240315P00045000', 'XLF', '2024-03-15', 'P', 45)")
    testdb.execute("INSERT INTO market.option_bar_30m VALUES ('XLF240315P00045000', "
                   "'2024-02-01 19:30+00', 1, 1, 1, 1.0, 10, 1, 1)")
    from datetime import UTC, datetime
    cutoff = datetime(2024, 2, 1, 20, 14, tzinfo=UTC)
    live._trade_options(testdb, dep, {"XLF240315P00045000": -5}, account, ["XLF"],
                        lambda *a, **kw: sent.append((a, kw)), cutoff)
    # Five $4,500 puts need $22,500; the deployment has $20,000.
    assert sent == []
    live._trade_options(testdb, dep, {"XLF240315P00045000": -4}, account, ["XLF"],
                        lambda *a, **kw: sent.append((a, kw)), cutoff)
    assert sent == [(("XLF240315P00045000", "sell", "opt"), {"qty": 4, "limit_price": 0.95})]
    live._trade_options(testdb, dep, {"SPY240315P00400000": -1}, account, ["XLF"],
                        lambda *a, **kw: sent.append((a, kw)), cutoff)
    assert len(sent) == 1


def test_old_strategies_with_a_computed_universe_still_parse():
    code = CODE.replace("    def decide(self, as_of, data):\n        return {\"B\": 0.5}\n",
                        "    def on_bar(self, ctx, bar):\n        pass\n").replace(
        'universe = ["A", "B"]', "universe = SYMBOLS")
    assert lab.inspect_code("SYMBOLS = ['A']\n" + code).error is None
