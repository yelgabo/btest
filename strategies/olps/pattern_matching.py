from btest.olps import OnlineStrategy, PatternMatching


class PatternMatchingStrategy(OnlineStrategy):
    """Pattern matching: finds past days whose preceding window of price ratios resembles the latest
    window, then picks the portfolio that did best on the days that followed. selection:
    histogram, kernel, nearest_neighbor or correlation; optimizer: log_optimal, semi_log_optimal
    or markowitz. Defaults are the paper's best combination (histogram + semi-log-optimal, about
    610x with a -75% drawdown, no costs). Slow: each session re-searches the whole history."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"selection": "histogram", "optimizer": "semi_log_optimal", "w": 4, "threshold": 0.1,
              "num_neighbors": 3, "rho": 0.6, "lambda_": 0.7}

    def make(self, n):
        return PatternMatching(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
