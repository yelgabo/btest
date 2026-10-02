from datetime import date
from importlib import resources

import polars as pl
import psycopg

from btest.calendar import SESSION_SCHEMA
from btest.sources.base import Dividend, Split


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url)


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migration "
                 "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    done = {r[0] for r in conn.execute("SELECT name FROM public.schema_migration")}
    applied = []
    files = sorted(f for f in resources.files("btest.sql").iterdir() if f.name.endswith(".sql"))
    for f in files:
        if f.name in done:
            continue
        conn.execute(f.read_text())
        conn.execute("INSERT INTO public.schema_migration (name) VALUES (%s)", (f.name,))
        applied.append(f.name)
    conn.commit()
    return applied


def symbol_id(conn: psycopg.Connection, ticker: str) -> int:
    row = conn.execute(
        "INSERT INTO market.symbol (ticker) VALUES (%s) "
        "ON CONFLICT (ticker) DO UPDATE SET ticker = EXCLUDED.ticker RETURNING id",
        (ticker,),
    ).fetchone()
    return row[0]


def upsert_splits(conn: psycopg.Connection, ticker: str, source: str,
                  splits: list[Split]) -> None:
    sid = symbol_id(conn, ticker)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.split (symbol_id, ex_date, old_rate, new_rate, source, source_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (source, source_id) DO UPDATE SET "
            "ex_date = EXCLUDED.ex_date, old_rate = EXCLUDED.old_rate, "
            "new_rate = EXCLUDED.new_rate",
            [(sid, s.ex_date, s.old_rate, s.new_rate, source, s.source_id) for s in splits],
        )


def upsert_dividends(conn: psycopg.Connection, ticker: str, source: str,
                     dividends: list[Dividend]) -> None:
    sid = symbol_id(conn, ticker)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.dividend (symbol_id, ex_date, rate, special, source, source_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (source, source_id) DO UPDATE SET "
            "ex_date = EXCLUDED.ex_date, rate = EXCLUDED.rate, special = EXCLUDED.special",
            [(sid, d.ex_date, d.rate, d.special, source, d.source_id) for d in dividends],
        )


def upsert_sessions(conn: psycopg.Connection, sessions: pl.DataFrame) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.session (date, open_utc, close_utc) VALUES (%s, %s, %s) "
            "ON CONFLICT (date) DO UPDATE SET open_utc = EXCLUDED.open_utc, "
            "close_utc = EXCLUDED.close_utc",
            sessions.select("date", "open_utc", "close_utc").rows(),
        )


def get_splits(conn: psycopg.Connection, ticker: str) -> list[Split]:
    rows = conn.execute(
        "SELECT s.ex_date, s.old_rate, s.new_rate, s.source_id FROM market.split s "
        "JOIN market.symbol y ON y.id = s.symbol_id WHERE y.ticker = %s ORDER BY s.ex_date",
        (ticker,),
    ).fetchall()
    return [Split(r[0], float(r[1]), float(r[2]), r[3]) for r in rows]


def get_dividends(conn: psycopg.Connection, ticker: str) -> list[Dividend]:
    rows = conn.execute(
        "SELECT d.ex_date, d.rate, d.special, d.source_id FROM market.dividend d "
        "JOIN market.symbol y ON y.id = d.symbol_id WHERE y.ticker = %s ORDER BY d.ex_date",
        (ticker,),
    ).fetchall()
    return [Dividend(r[0], float(r[1]), r[2], r[3]) for r in rows]


def get_sessions(conn: psycopg.Connection, start: date, end: date) -> pl.DataFrame:
    rows = conn.execute(
        "SELECT date, open_utc, close_utc FROM market.session "
        "WHERE date BETWEEN %s AND %s ORDER BY date",
        (start, end),
    ).fetchall()
    return pl.DataFrame(rows, schema=SESSION_SCHEMA, orient="row")
