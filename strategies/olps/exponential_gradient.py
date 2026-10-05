from btest.olps import OnlineStrategy, ExponentialGradient


class ExponentialGradientStrategy(OnlineStrategy):
    """Exponential gradient (Helmbold et al. 1998): tilts weights toward assets that beat the
    portfolio, scaled by learning_rate. smoothing = 1.0 is the published algorithm; the NYU paper
    used 0.0, which never moves the weights (its EG result equals CRP)."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"learning_rate": 0.05, "smoothing": 1.0}

    def make(self, n):
        return ExponentialGradient(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
