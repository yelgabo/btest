"""Option contracts and 30-minute option bars: fetched from Alpaca into Postgres, and read
back point-in-time for portfolio backtests and live decisions."""

import bisect
from datetime import UTC, date, datetime, timedelta

import polars as pl
import psycopg

from btest.ingest import log
from btest.portfolio import parse_occ
from btest.sources.alpaca import SIP_DELAY

BAR_MINUTES = 30
# Alpaca's option history starts in February 2024.
OPTION_HISTORY_START = date(2024, 2, 1)


def monthly_expiries(expiries: set[date]) -> set[date]:
    """Standard monthly expiries among those listed: the third Friday of each month, or the
    Thursday before it when that Friday is a holiday (then no Friday contracts exist)."""
    out = set()
    by_month: dict[tuple[int, int], list[date]] = {}
    for e in expiries:
        by_month.setdefault((e.year, e.month), []).append(e)
    for days in by_month.values():
        fridays = [e for e in days if e.weekday() == 4 and 15 <= e.day <= 21]
        thursdays = [e for e in days if e.weekday() == 3 and 14 <= e.day <= 20]
        out.update(fridays or thursdays[:1])
    return out


def contracts(source, underlying: str, start: date, end: date,
              option_type: str = "put") -> list[dict]:
    rows = []
    for status in ("inactive", "active"):
        token = None
        while True:
            params = {"underlying_symbols": underlying, "status": status, "type": option_type,
                      "expiration_date_gte": start.isoformat(),
                      "expiration_date_lte": end.isoformat(), "limit": 10000}
            if token:
                params["page_token"] = token
            page = source._get_trading("/v2/options/contracts", params)
            rows.extend(page.get("option_contracts") or [])
            token = page.get("next_page_token")
            if not token:
                break
    return rows


def ingest_options(conn: psycopg.Connection, source, underlying: str, start: date, end: date,
                   underlying_closes: pl.DataFrame, band: tuple[float, float] = (0.75, 1.05),
                   lead_days: int = 60) -> int:
    """Monthly puts within `band` of the underlying's price when each expiry was `lead_days`
    away, with 30-minute bars over that window. Returns bars written."""
    listed = contracts(source, underlying, start, end)
    monthly = monthly_expiries({date.fromisoformat(c["expiration_date"]) for c in listed})
    found = [c for c in listed if date.fromisoformat(c["expiration_date"]) in monthly]
    by_expiry: dict[date, list[dict]] = {}
    for c in found:
        by_expiry.setdefault(date.fromisoformat(c["expiration_date"]), []).append(c)
    dates = underlying_closes["date"].to_list()
    closes = underlying_closes["close"].to_list()
    written = 0
    for n, (expiry, items) in enumerate(sorted(by_expiry.items()), 1):
        listed = expiry - timedelta(days=lead_days)
        k = max(bisect.bisect_right(dates, max(listed, dates[0])) - 1, 0)
        ref = closes[k]
        keep = [c for c in items if band[0] * ref <= float(c["strike_price"]) <= band[1] * ref]
        conn.cursor().executemany(
            "INSERT INTO market.option_contract (symbol, underlying, expiry, option_type, strike) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (symbol) DO NOTHING",
            [(c["symbol"], underlying, expiry, "P" if c["type"] == "put" else "C",
              float(c["strike_price"])) for c in keep])
        bars = []
        bar_start = datetime.combine(listed, datetime.min.time(), UTC)
        # The free data plan refuses requests that reach into the last 15 minutes.
        bar_end = min(datetime.combine(expiry + timedelta(days=1), datetime.min.time(), UTC),
                      (datetime.now(UTC) - SIP_DELAY).replace(second=0, microsecond=0))
        if bar_end <= bar_start:
            continue
        for i in range(0, len(keep), 100):
            batch = [c["symbol"] for c in keep[i:i + 100]]
            bars += source.option_bars(batch, bar_start, bar_end, f"{BAR_MINUTES}Min")
        conn.cursor().executemany(
            "INSERT INTO market.option_bar_30m (symbol, ts, open, high, low, close, volume, "
            "trades, vwap) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (symbol, ts) DO UPDATE SET close = EXCLUDED.close, "
            "volume = EXCLUDED.volume, trades = EXCLUDED.trades, vwap = EXCLUDED.vwap", bars)
        conn.commit()
        written += len(bars)
        log(f"[{n}/{len(by_expiry)} {100 * n / len(by_expiry):.0f}%] {underlying} {expiry}: "
            f"{len(keep)} puts near {ref:.2f}, {len(bars):,} bars")
    return written


class OptionBook:
    """Option prices for the engine, loaded per underlying on first use. A bar counts as known
    once it has ended, so a decision at the cutoff never sees a bar still in progress."""

    def __init__(self, conn: psycopg.Connection, end: datetime | None = None):
        self._conn = conn
        self._end = end
        self._contracts: dict[str, pl.DataFrame] = {}
        self._bars: dict[str, pl.DataFrame] = {}
        self._by_symbol: dict[str, pl.DataFrame] = {}
        self._ends: dict[str, list[datetime]] = {}

    def _load(self, underlying: str) -> None:
        if underlying in self._contracts:
            return
        rows = self._conn.execute(
            "SELECT symbol, expiry, option_type, strike FROM market.option_contract "
            "WHERE underlying = %s ORDER BY expiry, strike", (underlying,)).fetchall()
        self._contracts[underlying] = pl.DataFrame(
            rows, schema={"symbol": pl.Utf8, "expiry": pl.Date, "option_type": pl.Utf8,
                          "strike": pl.Float64}, orient="row")
        where, params = "c.underlying = %s", [underlying]
        if self._end is not None:
            where += " AND b.ts < %s"
            params.append(self._end)
        bars = self._conn.execute(
            "SELECT b.symbol, b.ts, b.high, b.low, b.close, b.volume, b.vwap "
            "FROM market.option_bar_30m b "
            f"JOIN market.option_contract c ON c.symbol = b.symbol WHERE {where} "
            "ORDER BY b.symbol, b.ts", params).fetchall()
        df = pl.DataFrame(bars, schema={"symbol": pl.Utf8, "ts": pl.Datetime("us", "UTC"),
                                        "high": pl.Float64, "low": pl.Float64,
                                        "close": pl.Float64, "volume": pl.Float64,
                                        "vwap": pl.Float64}, orient="row")
        df = df.with_columns((pl.col("ts") + pl.duration(minutes=BAR_MINUTES)).alias("ends"))
        self._bars[underlying] = df
        for (sym,), part in df.group_by("symbol"):
            part = part.sort("ts")
            self._by_symbol[sym] = part
            self._ends[sym] = part["ends"].to_list()

    def expiries(self, underlying: str) -> list[date]:
        """Expiries with at least one bar; contracts listed without any trades are left out."""
        self._load(underlying)
        traded = set(self._bars[underlying]["symbol"].unique().to_list())
        con = self._contracts[underlying].filter(pl.col("symbol").is_in(list(traded)))
        return sorted(set(con["expiry"].to_list()))

    def chain(self, underlying: str, expiry: date, right: str, cutoff: datetime) -> pl.DataFrame:
        self._load(underlying)
        known_by = cutoff + timedelta(minutes=1)
        day_start = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
        con = self._contracts[underlying].filter((pl.col("expiry") == expiry)
                                                 & (pl.col("option_type") == right))
        bars = self._bars[underlying].filter(pl.col("symbol").is_in(con["symbol"].implode())
                                             & (pl.col("ends") <= known_by))
        last = bars.group_by("symbol").agg(pl.col("close").sort_by("ts").last().alias("price"))
        today = (bars.filter(pl.col("ts") >= day_start).group_by("symbol")
                 .agg(pl.col("volume").sum()))
        return (con.join(last, on="symbol", how="inner").join(today, on="symbol", how="left")
                .select("symbol", "strike", "price", pl.col("volume").fill_null(0.0))
                .sort("strike"))

    def reference(self, symbol: str, cutoff: datetime) -> float | None:
        """Close of the last bar that ended by the cutoff, if it traded today. The live order
        run prices its limit from the same bar."""
        self._load(parse_occ(symbol).underlying)
        df = self._by_symbol.get(symbol)
        if df is None:
            return None
        k = bisect.bisect_right(self._ends[symbol], cutoff + timedelta(minutes=1))
        if k == 0 or df["ts"][k - 1].date() != cutoff.date():
            return None
        return df["close"][k - 1]

    def fills_at(self, symbol: str, fill_ts: datetime, limit: float, delta: int) -> bool:
        """Whether a limit order resting at the fill time would have filled: the bar holding
        that time traded at or through the limit."""
        df = self._by_symbol.get(symbol)
        if df is None:
            return False
        hit = df.filter((pl.col("ts") <= fill_ts) & (pl.col("ends") > fill_ts))
        if hit.is_empty():
            return False
        row = hit.row(0, named=True)
        return row["high"] >= limit if delta < 0 else row["low"] <= limit

    def mark(self, symbol: str, ts: datetime) -> float | None:
        self._load(parse_occ(symbol).underlying)
        df = self._by_symbol.get(symbol)
        if df is None:
            return None
        k = bisect.bisect_right(self._ends[symbol], ts + timedelta(minutes=1))
        return df["close"][k - 1] if k > 0 else None
