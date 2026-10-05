from btest.olps import OnlineStrategy, PAMRAuthors


class PAMRPaperStrategy(OnlineStrategy):
    """PAMR exactly as the NYU paper's code runs it (clip and renormalize, previous target weights).
    olps/pamr is Li et al.'s PAMR-1 with the same settings. Paper: 788x vs CRP 12.16x, no costs."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"epsilon": 0.9, "C": 10.0}

    def make(self, n):
        return PAMRAuthors(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
