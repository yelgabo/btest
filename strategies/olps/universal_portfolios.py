from btest.olps import OnlineStrategy, UniversalPortfolios


class UniversalPortfoliosStrategy(OnlineStrategy):
    """Cover's universal portfolio, approximated by num_portfolios random portfolios weighted by
    wealth ** tau (the NYU paper's version, seeded so runs repeat). Paper: 12.42x vs CRP 12.16x."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"num_portfolios": 3, "tau": 0.3, "seed": 0}

    def make(self, n):
        return UniversalPortfolios(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
