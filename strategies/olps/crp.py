from btest.strategy import Strategy


class ConstantRebalanced(Strategy):
    """Constant rebalanced portfolio: equal weight in every symbol with data, reset either every
    session or only at month end. The paper's simplest benchmark beat buy-and-hold (12.2x vs
    9.2x, 1998-2010) by selling what rose and buying what fell back to equal weights."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    rebalance = "daily"
    params = {"monthly": True}

    def decide(self, as_of, data):
        if self.params["monthly"] and data.month_position()[1] != 1 and data.positions():
            return None
        live = [s for s in self.universe if len(data.history(s, "close", 2)) == 2]
        return {s: 1.0 / len(live) for s in live} if live else None
