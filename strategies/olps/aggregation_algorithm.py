from btest.olps import OnlineStrategy, AggregationAlgorithm


class AggregationAlgorithmStrategy(OnlineStrategy):
    """Vovk's aggregation algorithm on the assets themselves, mixed with equal weights by gamma.
    At the paper's settings it stays very close to CRP (12.15x vs 12.16x)."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"learning_rate": 0.005, "gamma": 0.3}

    def make(self, n):
        return AggregationAlgorithm(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
