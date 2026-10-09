from btest.olps import OnlineStrategy, UniversalPortfolios


class UniversalPortfoliosStrategy(OnlineStrategy):
    """The NYU paper's stand-in for Cover's universal portfolio: num_portfolios random portfolios
    (3 by default) weighted by wealth ** tau, seeded so runs repeat. Too few samples to approximate
    Cover's integral over the simplex; kept to replicate the paper (12.42x vs CRP 12.16x)."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"num_portfolios": 3, "tau": 0.3, "seed": 0}

    def make(self, n):
        return UniversalPortfolios(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
