from btest.olps import CWMRAuthors, OnlineStrategy


class CWMRMonthlyBars(OnlineStrategy):
    """The NYU paper's CWMR learning from month-over-month price ratios and trading at each month
    end, so winners and losers are judged over the same month it holds."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    bars = "monthly"
    rebalance = "month_end"
    params = {"epsilon": 0.89, "theta": 0.92, "eta": 0.93}

    def make(self, n):
        return CWMRAuthors(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
