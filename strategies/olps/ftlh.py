from btest.olps import OnlineStrategy, FollowTheLeadingHistory


class FTLHStrategy(OnlineStrategy):
    """Follow the leading history (Hazan and Seshadhri): starts a new online-Newton-step expert each
    session, combines them by weighted majority, drops experts below drop_threshold. Paper:
    16.5x vs CRP 12.16x."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"eta": 0.35, "learning_rate": 0.07, "drop_threshold": 0.55}

    def make(self, n):
        return FollowTheLeadingHistory(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
