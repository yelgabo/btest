import time
from datetime import date, datetime, timedelta

import httpx
import polars as pl

from btest.sources.base import BAR_SCHEMA, Dividend, Split

DATA_URL = "https://data.alpaca.markets"
# The free plan rejects SIP requests that reach into the most recent 15 minutes.
SIP_DELAY = timedelta(minutes=16)
RETRY_STATUS = {429, 500, 502, 503, 504}


class AlpacaSource:
    name = "alpaca"

    def __init__(self, key: str, secret: str, client: httpx.Client | None = None,
                 sleep=time.sleep, max_retries: int = 6):
        self._client = client or httpx.Client(base_url=DATA_URL, timeout=60)
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self._sleep = sleep
        self._max_retries = max_retries

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self._max_retries + 1):
            resp = self._client.get(path, params=params, headers=self._headers)
            if resp.status_code not in RETRY_STATUS or attempt == self._max_retries:
                resp.raise_for_status()
                return resp.json()
            self._sleep(min(2 ** attempt, 60))
        raise AssertionError("unreachable")

    def _pages(self, path: str, params: dict):
        token = None
        while True:
            page = self._get(path, params | ({"page_token": token} if token else {}))
            yield page
            token = page.get("next_page_token")
            if not token:
                return

    def bars(self, symbol: str, start: datetime, end: datetime,
             adjustment: str = "raw") -> pl.DataFrame:
        params = {
            "timeframe": "1Min",
            "start": _iso(start),
            "end": _iso(end),
            "feed": "sip",
            "adjustment": adjustment,
            "limit": 10000,
            "sort": "asc",
        }
        rows = []
        for page in self._pages(f"/v2/stocks/{symbol}/bars", params):
            rows.extend(page.get("bars") or [])
        if not rows:
            return pl.DataFrame(schema=BAR_SCHEMA)
        df = pl.DataFrame(rows).rename({
            "t": "ts", "o": "open", "h": "high", "l": "low", "c": "close",
            "v": "volume", "n": "trades", "vw": "vwap",
        })
        return df.with_columns(
            pl.col("ts").str.to_datetime(time_zone="UTC", time_unit="us"),
        ).select([pl.col(c).cast(t) for c, t in BAR_SCHEMA.items()])

    def _actions(self, symbol: str, types: str, start: date, end: date) -> dict[str, list]:
        params = {"symbols": symbol, "types": types, "start": start.isoformat(),
                  "end": end.isoformat(), "limit": 1000}
        out: dict[str, list] = {}
        for page in self._pages("/v1/corporate-actions", params):
            for kind, items in (page.get("corporate_actions") or {}).items():
                out.setdefault(kind, []).extend(items)
        return out

    def splits(self, symbol: str, start: date, end: date) -> list[Split]:
        acts = self._actions(symbol, "forward_split,reverse_split", start, end)
        items = acts.get("forward_splits", []) + acts.get("reverse_splits", [])
        return [
            Split(date.fromisoformat(a["ex_date"]), float(a["old_rate"]), float(a["new_rate"]),
                  a["id"])
            for a in items
        ]

    def dividends(self, symbol: str, start: date, end: date) -> list[Dividend]:
        acts = self._actions(symbol, "cash_dividend", start, end)
        return [
            Dividend(date.fromisoformat(a["ex_date"]), float(a["rate"]), bool(a["special"]),
                     a["id"])
            for a in acts.get("cash_dividends", [])
        ]


def _iso(ts: datetime) -> str:
    if ts.utcoffset() != timedelta(0):
        raise ValueError(f"expected a UTC datetime, got {ts!r}")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
