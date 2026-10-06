from btest.strategy import Strategy


class BuyAndHold(Strategy):
    """Puts the whole account in one symbol on the first session and holds it, buying more with
    dividends as they arrive, so it earns the total return. The yardstick every other strategy
    has to beat after costs."""

    universe = ["SPY"]
    rebalance = "daily"
    params = {"symbol": "SPY"}

    def decide(self, as_of, data):
        symbol = self.params["symbol"]
        # A threshold, not any cash, so the residue left after each purchase does not trade daily.
        if data.position(symbol) and data.cash < 0.001 * data.equity:
            return None
        return {symbol: 1.0}
