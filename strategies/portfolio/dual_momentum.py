from btest.strategy import Strategy


class DualMomentum(Strategy):
    """Antonacci's global equities momentum: hold US or international stocks, whichever rose
    more over the lookback, but only while that return beats T-bills (BIL); otherwise hold
    bonds. Checked at each month end."""

    universe = ["SPY", "EFA", "AGG", "BIL"]
    rebalance = "month_end"
    params = {"lookback": 252, "us": "SPY", "intl": "EFA", "bonds": "AGG", "bills": "BIL"}

    def validate(self):
        if self.params["lookback"] < 21:
            raise ValueError("lookback must be at least 21 sessions")

    def _ret(self, data, symbol):
        close = data.history(symbol, "close", self.params["lookback"] + 1)
        if len(close) <= self.params["lookback"]:
            return None
        return close[-1] / close[0] - 1

    def decide(self, as_of, data):
        p = self.params
        us, intl, bills = (self._ret(data, p[k]) for k in ("us", "intl", "bills"))
        if us is None or intl is None or bills is None:
            return None
        best, best_ret = (p["us"], us) if us >= intl else (p["intl"], intl)
        pick = best if best_ret > bills else p["bonds"]
        # Hold until the pick changes; topping up each month would only trade dividend cash.
        if set(data.positions()) == {pick}:
            return None
        return {pick: 1.0}
