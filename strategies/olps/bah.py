from btest.strategy import Strategy


class EqualWeightBuyAndHold(Strategy):
    """Buys every symbol in equal dollar amounts on the first session and never rebalances: the
    paper's buy-and-hold benchmark (9.17x, 1998-2009)."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {}

    def decide(self, as_of, data):
        if data.positions():
            return None
        live = [s for s in self.universe if len(data.history(s, "close", 1))]
        return {s: 1.0 / len(live) for s in live}
