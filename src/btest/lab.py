"""Strategies stored in Postgres, and the jobs that run them. Nothing here executes strategy
code; the web service only parses it."""

import ast
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from btest.bars import TIMEFRAMES
from btest.config import Settings
from btest.portfolio import SCHEDULES
from btest.sweep import parse_grid

NAME_RE = re.compile(r"^[a-z0-9_]+(/[a-z0-9_]+)*$")
MAX_COMBOS = 5000
COST_KEYS = {"cash", "slippage_bps", "commission_per_share", "sec_fee_rate", "allow_short"}
# Portfolio (decide) runs only.
FLAG_KEYS = {"fractional", "cash_yield"}
BENCHMARKS = ("SPY", "60/40")

# What "New strategy" opens with: every hook and call, commented.
TEMPLATE = (Path(__file__).parent / "templates" / "strategy_template.py").read_text()

# A minimal working strategy, used by tests.
EXAMPLE = '''import numpy as np

from btest.strategy import Strategy


class BuyAndHold(Strategy):
    """Buys once and holds. Replace on_bar with your own logic."""

    params = {"symbol": "SPY", "allocation": 1.0}

    def on_bar(self, ctx, bar):
        if bar.symbol == self.params["symbol"] and ctx.position(bar.symbol) == 0:
            ctx.order_target_percent(bar.symbol, self.params["allocation"])

    def signals(self, a):
        # Fast path for sweeps: target weight per bar, NaN means no change.
        w = np.full(len(a["close"]), np.nan)
        w[0] = self.params["allocation"]
        return w
'''


INDICATOR_TEMPLATE = '''import numpy as np

from btest.indicator import Indicator


class RSI(Indicator):
    """Relative strength index with Wilder's smoothing, 0 to 100."""

    params = {"length": 14}
    pane = "own"
    levels = [30, 70]

    def compute(self, c):
        n = self.params["length"]
        close = c["close"]
        delta = np.diff(close, prepend=close[0])
        gain, loss = np.clip(delta, 0, None), np.clip(-delta, 0, None)
        rsi = np.full(len(close), np.nan)
        if len(close) <= n:
            return {"rsi": rsi}
        avg_gain, avg_loss = gain[1:n + 1].mean(), loss[1:n + 1].mean()
        for i in range(n, len(close)):
            if i > n:
                avg_gain = (avg_gain * (n - 1) + gain[i]) / n
                avg_loss = (avg_loss * (n - 1) + loss[i]) / n
            rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        return {"rsi": rsi}
'''

BASES = {"strategy": "Strategy", "indicator": "Indicator"}


@dataclass
class Inspection:
    class_name: str | None
    params: dict
    has_signals: bool
    error: str | None
    error_line: int | None
    pane: str = "price"
    levels: list | None = None
    timeframe: str = "1m"
    has_decide: bool = False
    universe: list | None = None
    rebalance: str = "daily"


def _literal(cls: ast.ClassDef, name: str):
    for node in cls.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return ast.literal_eval(node.value), node.lineno
    return None, None


def inspect_code(code: str, kind: str = "strategy") -> Inspection:
    """Read the Strategy or Indicator subclass and its literal settings (params, and for
    indicators pane and levels) without running the code."""
    base = BASES[kind]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return Inspection(None, {}, False, f"SyntaxError: {e.msg}", e.lineno)
    # Base classes from btest such as olps.OnlineStrategy count too: any name ending in the
    # base's name.
    classes = [
        n for n in tree.body if isinstance(n, ast.ClassDef)
        and any((isinstance(b, ast.Name) and b.id.endswith(base))
                or (isinstance(b, ast.Attribute) and b.attr.endswith(base)) for b in n.bases)
    ]
    if len(classes) != 1:
        return Inspection(None, {}, False,
                          f"Expected one class that subclasses {base}, found {len(classes)}.",
                          None)
    cls = classes[0]
    values = {}
    portfolio_errors = {}
    for name, rule in (("params", "a literal dict (numbers, strings, booleans)"),
                       ("pane", '"price" or "own"'), ("levels", "a literal list of numbers"),
                       ("timeframe", 'one of "1m", "5m", "15m", "30m", "1h", "1D"'),
                       ("universe", "a literal list of symbols"),
                       ("rebalance", '"daily", "weekly", "month_end" or "month_start"')):
        try:
            values[name], _ = _literal(cls, name)
        except ValueError:
            # universe and rebalance only matter to decide() strategies; checked below.
            if name in ("universe", "rebalance"):
                values[name] = None
                portfolio_errors[name] = f"{name} must be {rule}."
                continue
            return Inspection(cls.name, {}, False, f"{name} must be {rule}.",
                              _literal_line(cls, name))
    params = values["params"] if isinstance(values["params"], dict) else {}
    has_signals = any(isinstance(n, ast.FunctionDef) and n.name == "signals" for n in cls.body)
    pane = values["pane"] if values["pane"] in ("price", "own") else "price"
    levels = [v for v in (values["levels"] or []) if isinstance(v, (int, float))]
    if kind == "indicator" and not any(isinstance(n, ast.FunctionDef) and n.name == "compute"
                                       for n in cls.body):
        return Inspection(cls.name, params, False, "Add a compute(self, c) method.", cls.lineno,
                          pane, levels)
    timeframe = values["timeframe"] if isinstance(values["timeframe"], str) else "1m"
    if kind == "strategy" and timeframe not in TIMEFRAMES:
        return Inspection(cls.name, params, has_signals,
                          f"timeframe must be one of {', '.join(TIMEFRAMES)}.",
                          _literal_line(cls, "timeframe"), pane, levels, timeframe)
    has_decide = any(isinstance(n, ast.FunctionDef) and n.name == "decide" for n in cls.body)
    universe = [str(x).upper() for x in values["universe"] or [] if isinstance(x, str)]
    rebalance = values["rebalance"] if isinstance(values["rebalance"], str) else "daily"
    if kind == "strategy" and has_decide:
        error = next(iter(portfolio_errors.values()), None)
        if error is None and not universe:
            error = "A strategy with decide() needs universe = [\"SPY\", ...]."
        elif error is None and rebalance not in SCHEDULES:
            error = f"rebalance must be one of {', '.join(SCHEDULES)}."
        if error:
            line = _literal_line(cls, "universe" if not universe else "rebalance") or cls.lineno
            return Inspection(cls.name, params, has_signals, error, line, pane, levels,
                              timeframe, has_decide, universe, rebalance)
    return Inspection(cls.name, params, has_signals, None, None, pane, levels, timeframe,
                      has_decide, universe, rebalance)


def _literal_line(cls: ast.ClassDef, name: str) -> int | None:
    for node in cls.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return node.lineno
    return None


def sha256(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def check_name(name: str) -> str:
    name = name.strip().strip("/").lower()
    if name.endswith(".py"):
        name = name[:-3]
    if not NAME_RE.match(name):
        raise ValueError("Use lowercase letters, digits and underscores, with / between "
                         "folders, e.g. trend/ma_cross.")
    return name


def list_strategies(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id, s.name, s.updated_at, v.version, s.kind, "
        "(SELECT count(*) FROM runs.run r JOIN lab.strategy_version sv "
        " ON sv.id = r.strategy_version_id WHERE sv.strategy_id = s.id) "
        "FROM lab.strategy s JOIN LATERAL (SELECT version FROM lab.strategy_version "
        " WHERE strategy_id = s.id ORDER BY version DESC LIMIT 1) v ON true "
        "WHERE NOT s.archived ORDER BY s.kind DESC, s.name"
    ).fetchall()
    return [{"id": r[0], "name": r[1], "updated_at": r[2], "version": r[3], "kind": r[4],
             "runs": r[5]} for r in rows]


def create(conn: psycopg.Connection, name: str, code: str | None = None,
           kind: str = "strategy") -> int:
    if kind not in BASES:
        raise ValueError("kind must be strategy or indicator.")
    name = check_name(name)
    exists = conn.execute("SELECT 1 FROM lab.strategy WHERE name = %s AND kind = %s "
                          "AND NOT archived", (name, kind)).fetchone()
    if exists:
        raise ValueError(f"{name} already exists.")
    folder_clash = conn.execute(
        "SELECT name FROM lab.strategy WHERE NOT archived AND kind = %s AND "
        "(name LIKE %s OR %s LIKE name || '/%%')",
        (kind, name + "/%", name),
    ).fetchone()
    if folder_clash:
        raise ValueError(f"{name} would clash with {folder_clash[0]}: a name cannot be both a "
                         "strategy and a folder.")
    if code is None:
        code = TEMPLATE if kind == "strategy" else INDICATOR_TEMPLATE
    sid = conn.execute("INSERT INTO lab.strategy (name, kind) VALUES (%s, %s) RETURNING id",
                       (name, kind)).fetchone()[0]
    conn.execute("INSERT INTO lab.strategy_version (strategy_id, version, code, sha256) "
                 "VALUES (%s, 1, %s, %s)", (sid, code, sha256(code)))
    conn.commit()
    return sid


def get(conn: psycopg.Connection, sid: int, version: int | None = None) -> dict | None:
    s = conn.execute("SELECT id, name, created_at, updated_at, kind FROM lab.strategy "
                     "WHERE id = %s AND NOT archived", (sid,)).fetchone()
    if s is None:
        return None
    versions = conn.execute(
        "SELECT v.id, v.version, v.created_at, v.sha256, "
        "(SELECT count(*) FROM runs.run r WHERE r.strategy_version_id = v.id) "
        "FROM lab.strategy_version v WHERE strategy_id = %s ORDER BY version DESC", (sid,),
    ).fetchall()
    want = version or versions[0][1]
    row = conn.execute("SELECT id, version, code FROM lab.strategy_version "
                       "WHERE strategy_id = %s AND version = %s", (sid, want)).fetchone()
    if row is None:
        return None
    info = inspect_code(row[2], s[4])
    return {
        "id": s[0], "name": s[1], "created_at": s[2], "updated_at": s[3], "kind": s[4],
        "pane": info.pane, "levels": info.levels or [], "timeframe": info.timeframe,
        "version_id": row[0], "version": row[1], "latest": versions[0][1], "code": row[2],
        "class_name": info.class_name, "params": info.params, "has_signals": info.has_signals,
        "has_decide": info.has_decide, "universe": info.universe or [],
        "rebalance": info.rebalance,
        "parse_error": info.error, "parse_error_line": info.error_line,
        "versions": [{"id": v[0], "version": v[1], "created_at": v[2], "sha256": v[3],
                      "runs": v[4]} for v in versions],
    }


def save(conn: psycopg.Connection, sid: int, code: str, base_version: int) -> int:
    """Store code as a new version. Returns the version now current. Saving identical code is
    a no-op; saving on top of a stale base is refused so two tabs cannot silently clobber."""
    latest = conn.execute(
        "SELECT version, sha256 FROM lab.strategy_version WHERE strategy_id = %s "
        "ORDER BY version DESC LIMIT 1 FOR UPDATE", (sid,),
    ).fetchone()
    if latest is None:
        raise LookupError(f"No strategy {sid}.")
    if latest[1] == sha256(code):
        conn.rollback()
        return latest[0]
    if base_version != latest[0]:
        conn.rollback()
        raise ValueError(f"Version {latest[0]} was saved since you opened version "
                         f"{base_version}. Reload to see it before saving.")
    version = latest[0] + 1
    conn.execute("INSERT INTO lab.strategy_version (strategy_id, version, code, sha256) "
                 "VALUES (%s, %s, %s, %s)", (sid, version, code, sha256(code)))
    conn.execute("UPDATE lab.strategy SET updated_at = now() WHERE id = %s", (sid,))
    conn.commit()
    return version


def rename(conn: psycopg.Connection, sid: int, name: str) -> None:
    name = check_name(name)
    clash = conn.execute(
        "SELECT name FROM lab.strategy WHERE NOT archived AND id <> %s "
        "AND kind = (SELECT kind FROM lab.strategy WHERE id = %s) AND "
        "(name = %s OR name LIKE %s OR %s LIKE name || '/%%')",
        (sid, sid, name, name + "/%", name),
    ).fetchone()
    if clash:
        raise ValueError(f"{name} clashes with {clash[0]}.")
    conn.execute("UPDATE lab.strategy SET name = %s, updated_at = now() WHERE id = %s",
                 (name, sid))
    conn.commit()


def archive(conn: psycopg.Connection, sid: int) -> None:
    conn.execute("UPDATE lab.strategy SET archived = true WHERE id = %s", (sid,))
    conn.commit()


def import_files(conn: psycopg.Connection, folder: Path, kind: str = "strategy") -> list[str]:
    """Add each .py file under folder that is not in the lab yet, named after its path."""
    added = []
    for path in sorted(folder.rglob("*.py")):
        name = check_name(str(path.relative_to(folder)))
        if conn.execute("SELECT 1 FROM lab.strategy WHERE name = %s AND kind = %s "
                        "AND NOT archived", (name, kind)).fetchone():
            continue
        create(conn, name, path.read_text(), kind)
        added.append(name)
    return added


def validate_spec(kind: str, spec: dict, settings: Settings, has_signals: bool,
                  universe: list[str] | None = None) -> dict:
    """Normalise a run or sweep request from the browser, or raise ValueError with a message
    the page can show. A strategy with a universe (one with decide()) always runs on it."""
    if kind not in ("run", "sweep"):
        raise ValueError("kind must be run or sweep.")
    out: dict = {}
    if universe and kind == "sweep":
        raise ValueError("Sweeps of decide() strategies need the portfolio fast path, which is "
                         "not built yet. Run single settings instead.")
    if universe:
        symbols = list(universe)
    elif kind == "run":
        symbols = spec.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [s for s in re.split(r"[\s,]+", symbols) if s]
    else:
        symbols = [spec.get("symbol", "")]
    symbols = [s.upper() for s in symbols]
    unknown = [s for s in symbols if s not in settings.symbols]
    if not symbols or unknown:
        raise ValueError(f"Symbols must come from {', '.join(settings.symbols)}"
                         + (f"; {', '.join(unknown)} has no data." if unknown else "."))
    try:
        start, end = date.fromisoformat(spec["start"]), date.fromisoformat(spec["end"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Start and end must be dates like 2016-01-01.") from None
    if start >= end:
        raise ValueError("Start must be before end.")
    if start < settings.history_start:
        raise ValueError(f"Data starts {settings.history_start}.")
    if kind == "run":
        if end > settings.holdout_start and not spec.get("spend_holdout"):
            raise ValueError(f"This window reaches the holdout (from {settings.holdout_start}). "
                             "Tick 'Use the holdout' if you mean to spend it.")
        out["symbols"] = symbols
    else:
        if end > settings.holdout_start:
            raise ValueError(f"Sweeps must end on or before {settings.holdout_start}, where "
                             "the holdout starts.")
        if not has_signals:
            raise ValueError("Sweeps use the fast path: add a signals() method first.")
        out["symbol"] = symbols[0]
        raw = spec.get("grid") or {}
        grid_specs = [f"{k}={v}" if isinstance(v, str) else f"{k}={','.join(map(str, v))}"
                      for k, v in raw.items() if str(v).strip()]
        if not grid_specs:
            raise ValueError("Give at least one parameter a list of values to sweep.")
        try:
            grid = parse_grid(grid_specs)
        except SystemExit as e:
            raise ValueError(str(e)) from None
        combos = 1
        for values in grid.values():
            combos *= len(values)
        if combos > MAX_COMBOS:
            raise ValueError(f"{combos:,} combinations; the limit is {MAX_COMBOS:,}.")
        out["grid"] = grid
    params = spec.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object.")
    out["params"] = {k: v for k, v in params.items() if kind == "run" or k not in out["grid"]}
    raw_config = spec.get("config") or {}
    costs = {k: v for k, v in raw_config.items() if k in COST_KEYS}
    if universe:
        costs.pop("allow_short", None)
        costs.update({k: bool(raw_config[k]) for k in FLAG_KEYS if k in raw_config})
        if "benchmark" in raw_config:
            if raw_config["benchmark"] not in BENCHMARKS:
                raise ValueError(f"benchmark must be one of {', '.join(BENCHMARKS)}.")
            costs["benchmark"] = raw_config["benchmark"]
    for k, v in costs.items():
        if k in FLAG_KEYS or k == "benchmark":
            continue
        if k == "allow_short":
            costs[k] = bool(v)
        elif not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"{k} must be a number of at least 0.")
    out["config"] = costs
    out["start"], out["end"] = start.isoformat(), end.isoformat()
    out["spend_holdout"] = bool(spec.get("spend_holdout")) and kind == "run"
    return out


def submit(conn: psycopg.Connection, version_id: int, kind: str, spec: dict) -> int:
    jid = conn.execute(
        "INSERT INTO lab.job (kind, strategy_version_id, spec) VALUES (%s, %s, %s) RETURNING id",
        (kind, version_id, Jsonb(spec)),
    ).fetchone()[0]
    conn.commit()
    return jid


def job(conn: psycopg.Connection, jid: int) -> dict | None:
    r = conn.execute(
        "SELECT j.id, j.kind, j.status, j.error, j.error_line, j.log, j.run_id, j.sweep_id, "
        "j.created_at, j.started_at, j.finished_at, j.spec, v.strategy_id, v.version, "
        "(SELECT count(*) FROM lab.job q WHERE q.status = 'queued' AND q.id < j.id) "
        "FROM lab.job j JOIN lab.strategy_version v ON v.id = j.strategy_version_id "
        "WHERE j.id = %s", (jid,),
    ).fetchone()
    if r is None:
        return None
    return {"id": r[0], "kind": r[1], "status": r[2], "error": r[3], "error_line": r[4],
            "log": r[5], "run_id": r[6], "sweep_id": r[7], "created_at": r[8],
            "started_at": r[9], "finished_at": r[10], "spec": r[11], "strategy_id": r[12],
            "version": r[13], "ahead": r[14]}


def recent_jobs(conn: psycopg.Connection, sid: int, limit: int = 15) -> list[dict]:
    rows = conn.execute(
        "SELECT j.id, j.kind, j.status, v.version, j.created_at, j.finished_at, j.run_id, "
        "j.sweep_id, j.error, r.metrics->>'sharpe', r.metrics->>'cagr', "
        "r.metrics->>'max_drawdown', j.spec "
        "FROM lab.job j JOIN lab.strategy_version v ON v.id = j.strategy_version_id "
        "LEFT JOIN runs.run r ON r.id = j.run_id "
        "WHERE v.strategy_id = %s ORDER BY j.id DESC LIMIT %s", (sid, limit),
    ).fetchall()
    return [{"id": r[0], "kind": r[1], "status": r[2], "version": r[3], "created_at": r[4],
             "finished_at": r[5], "run_id": r[6], "sweep_id": r[7], "error": r[8],
             "sharpe": None if r[9] is None else float(r[9]),
             "cagr": None if r[10] is None else float(r[10]),
             "max_drawdown": None if r[11] is None else float(r[11]), "spec": r[12]}
            for r in rows]
