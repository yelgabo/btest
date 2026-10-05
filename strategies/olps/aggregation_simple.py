from btest.olps import OnlineStrategy, AggregationSimple


class AggregationSimpleStrategy(OnlineStrategy):
    """Weights num_base_portfolios random portfolios by cumulative performance ** learning_rate
    (the NYU paper's version, seeded so runs repeat). Paper: 12.94x vs CRP 12.16x."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"learning_rate": 0.4, "num_base_portfolios": 3, "seed": 0}

    def make(self, n):
        return AggregationSimple(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
