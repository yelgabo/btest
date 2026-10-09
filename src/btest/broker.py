"""Alpaca trading API: account, positions, orders and account settings."""

import time

import httpx

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
RETRY_STATUS = {429, 500, 502, 503, 504}
# Alpaca has no cash account type; these settings make a margin account behave like one.
# Options level is left alone: the paper account refuses anything below 3 ("less than minimum
# allowed value 3", 2026-10-04), so cash-secured puts are enforced by btest instead.
CASH_ACCOUNT = {"max_margin_multiplier": "1", "no_shorting": True, "fractional_trading": True}


class BrokerError(RuntimeError):
    pass


class AlpacaBroker:
    def __init__(self, key: str, secret: str, paper: bool = True,
                 client: httpx.Client | None = None, sleep=time.sleep):
        self._client = client or httpx.Client(base_url=PAPER_URL if paper else LIVE_URL,
                                              timeout=30)
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self._sleep = sleep
        self.paper = paper

    def _call(self, method: str, path: str, **kw):
        # A POST that failed on the server side may still have created the order; submit()
        # checks by client order id instead of blindly retrying.
        tries = 1 if method == "POST" else 5
        for attempt in range(tries):
            resp = self._client.request(method, path, headers=self._headers, **kw)
            if resp.status_code in RETRY_STATUS and attempt < tries - 1:
                self._sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code >= 400:
                raise BrokerError(f"{method} {path}: {resp.status_code} {resp.text[:300]}")
            return resp.json() if resp.content else None
        raise AssertionError("unreachable")

    def account(self) -> dict:
        return self._call("GET", "/v2/account")

    def configurations(self) -> dict:
        return self._call("GET", "/v2/account/configurations")

    def configure(self, settings: dict) -> dict:
        return self._call("PATCH", "/v2/account/configurations", json=settings)

    def positions(self) -> list[dict]:
        return self._call("GET", "/v2/positions")

    def submit(self, symbol: str, side: str, client_order_id: str, notional: float | None = None,
               qty: float | None = None, limit_price: float | None = None) -> dict:
        body = {"symbol": symbol, "side": side, "time_in_force": "day",
                "client_order_id": client_order_id,
                "type": "limit" if limit_price is not None else "market"}
        if notional is not None:
            body["notional"] = f"{notional:.2f}"
        else:
            body["qty"] = f"{qty:.9f}".rstrip("0").rstrip(".")
        if limit_price is not None:
            body["limit_price"] = f"{limit_price:.2f}"
        try:
            return self._call("POST", "/v2/orders", json=body)
        except (BrokerError, httpx.TransportError):
            existing = self.order_by_client_id(client_order_id)
            if existing is not None:
                return existing
            raise

    def close_position(self, symbol: str, client_order_id: str) -> dict:
        """Sell the whole broker position, fractional part included. Only safe because
        live.deploy and live.enable refuse deployments whose universes overlap."""
        qty = next((float(p["qty"]) for p in self.positions() if p["symbol"] == symbol), 0.0)
        if qty <= 0:
            raise BrokerError(f"no long position in {symbol}")
        return self.submit(symbol, "sell", client_order_id, qty=qty)

    def order_by_client_id(self, client_order_id: str) -> dict | None:
        try:
            return self._call("GET", "/v2/orders:by_client_order_id",
                              params={"client_order_id": client_order_id})
        except BrokerError as e:
            if " 404 " in str(e):
                return None
            raise

    def cancel(self, order_id: str) -> None:
        self._call("DELETE", f"/v2/orders/{order_id}")

    def activities(self, types: str, after: str) -> list[dict]:
        """Non-trade activities such as option assignments (OPASN) and expiries (OPEXP). They
        are not pushed over the websocket, so the reconcile step polls for them."""
        return self._call("GET", "/v2/account/activities",
                          params={"activity_types": types, "after": after})
