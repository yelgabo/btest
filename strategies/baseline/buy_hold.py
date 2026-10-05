from btest.strategy import Strategy


class BuyAndHold(Strategy):
    """Puts the whole account in one symbol on the first session and holds it. The yardstick
    every other strategy has to beat after costs."""

    universe = ["SPY"]
    rebalance = "daily"
    params = {"symbol": "SPY"}

    def decide(self, as_of, data):
        symbol = self.params["symbol"]
        if data.position(symbol):
            return None
        return {symbol: 1.0}
