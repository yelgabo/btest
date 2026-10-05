from btest.strategy import Strategy


class TurnOfMonth(Strategy):
    """Holds SPY over the turn of the month: buys on the last session of a month and sells on
    the exit_day-th session of the next, cash (earning T-bills) the rest of the time."""

    universe = ["SPY"]
    rebalance = "daily"
    params = {"symbol": "SPY", "exit_day": 3}

    def validate(self):
        if self.params["exit_day"] < 1:
            raise ValueError("exit_day must be at least 1")

    def decide(self, as_of, data):
        symbol = self.params["symbol"]
        from_start, from_end = data.month_position()
        hold = from_end == 1 or from_start < self.params["exit_day"]
        if hold == bool(data.position(symbol)):
            return None
        return {symbol: 1.0} if hold else {}
