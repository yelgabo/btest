from btest.olps import OnlineStrategy, RMR


class RMRStrategy(OnlineStrategy):
    """Robust median reversion, the NYU paper's version (median of price ratios over the latest
    ratio; Huang et al. use prices). Paper: 18.9x vs CRP 12.16x."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"window_size": 8, "epsilon": 1.1, "eta": 30}

    def make(self, n):
        return RMR(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
