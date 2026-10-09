from btest.olps import CWMRAuthors, OnlineStrategy


class CWMRMonthly(OnlineStrategy):
    """The NYU paper's CWMR variant, learning from daily prices but trading only at each month
    end, about 14x its value a year. Chosen in a search on 2016-2024 minute data and
    pre-registered for the 2025 holdout, which it failed; on long history, 1999-2024, it trails
    equal weight and SPY (docs/research/paper/cwmr-etf.pdf, Sections 4 and 7)."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "month_end"
    params = {"epsilon": 0.89, "theta": 0.92, "eta": 0.93}

    def make(self, n):
        return CWMRAuthors(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
