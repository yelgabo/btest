from btest.olps import OnlineStrategy, FollowTheLeader


class FollowTheLeaderStrategy(OnlineStrategy):
    """Follow the leader, the NYU paper's version: weights proportional to each asset's cumulative
    growth ** alpha, blended with yesterday's weights by gamma. Paper: 8.44x vs CRP 12.16x."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"gamma": 0.8, "alpha": 1.5}

    def make(self, n):
        return FollowTheLeader(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
