from btest.olps import OnlineStrategy, FollowTheRegularizedLeader


class FTRLStrategy(OnlineStrategy):
    """Follow the regularized leader, the NYU paper's online-Newton-style version with a ridge term.
    Paper: 15.25x vs CRP 12.16x; on its tickers with complete data it trails CRP, and on ETFs it
    barely moves from equal weights."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"beta": 0.13, "delta": 0.925, "ridge_const": 0.015}

    def make(self, n):
        return FollowTheRegularizedLeader(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
