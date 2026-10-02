import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import psycopg

from btest import db, store
from btest.calendar import mark_regular, nyse_sessions
from btest.sources.alpaca import SIP_DELAY
from btest.sources.base import DataSource


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True, file=sys.stdout)


def sync_calendar(conn: psycopg.Connection, start: date) -> pl.DataFrame:
    sessions = nyse_sessions(start, date.today() + timedelta(days=365))
    db.upsert_sessions(conn, sessions)
    conn.commit()
    log(f"calendar: {sessions.height} sessions {sessions['date'][0]} to {sessions['date'][-1]}")
    return sessions


def sync_actions(conn: psycopg.Connection, source: DataSource, symbol: str,
                 start: date) -> None:
    end = date.today() + timedelta(days=90)
    splits = source.splits(symbol, start, end)
    dividends = source.dividends(symbol, start, end)
    db.upsert_splits(conn, symbol, source.name, splits)
    db.upsert_dividends(conn, symbol, source.name, dividends)
    conn.commit()
    log(f"{symbol}: {len(splits)} splits, {len(dividends)} dividends")


FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
RISK_FREE_SERIES = "DTB3"


def sync_risk_free(conn: psycopg.Connection, start: date) -> None:
    resp = httpx.get(FRED_CSV, params={"id": RISK_FREE_SERIES, "cosd": start.isoformat()},
                     timeout=60, follow_redirects=True)
    resp.raise_for_status()
    rows = []
    for line in resp.text.splitlines()[1:]:
        d, _, v = line.partition(",")
        # FRED leaves holidays blank or writes ".".
        if v.strip() not in ("", "."):
            rows.append((date.fromisoformat(d), float(v)))
    db.upsert_rates(conn, RISK_FREE_SERIES, rows)
    conn.commit()
    log(f"risk-free {RISK_FREE_SERIES}: {len(rows)} days through {rows[-1][0]}")


def year_chunks(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    chunks = []
    cur = start
    while cur < end:
        nxt = min(datetime(cur.year + 1, 1, 1, tzinfo=UTC), end)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


def ingest(conn: psycopg.Connection, source: DataSource, data_dir: Path,
           symbols: list[str], history_start: date) -> None:
    sessions = sync_calendar(conn, history_start)
    sync_risk_free(conn, history_start)
    end = (datetime.now(UTC) - SIP_DELAY).replace(second=0, microsecond=0)
    plan = []
    for symbol in symbols:
        sync_actions(conn, source, symbol, history_start)
        last = store.last_ts(data_dir, symbol)
        start = (last + timedelta(minutes=1) if last
                 else datetime.combine(history_start, datetime.min.time(), UTC))
        plan.extend((symbol, a, b) for a, b in year_chunks(start, end))
    log(f"bars: {len(plan)} chunks to fetch, through {end:%Y-%m-%d %H:%M}Z")
    for i, (symbol, a, b) in enumerate(plan, 1):
        bars = mark_regular(source.bars(symbol, a, b), sessions)
        store.write_bars(data_dir, symbol, bars)
        pct = 100 * i / len(plan)
        log(f"[{i}/{len(plan)} {pct:.0f}%] {symbol} {a:%Y-%m-%d} to {b:%Y-%m-%d}: "
            f"{bars.height:,} bars ({int(bars['regular'].sum()):,} regular)")
