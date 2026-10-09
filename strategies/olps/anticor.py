from btest.olps import OnlineStrategy, Anticor


class AnticorStrategy(OnlineStrategy):
    """Anticor, the NYU paper's simplified version: compares log price ratios over two consecutive
    windows and moves weight by alpha times the net cross-correlation above corr_threshold.
    Unlike Borodin, El-Yaniv and Gogan's Anticor, transfers are not scaled by holdings, and the
    correlation scale is inflated by w / (w - 1) as in the authors' code (see btest.olps.Anticor).
    Paper: 36.9x vs CRP 12.16x (no costs); it trades heavily, so costs bite."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"window_size": 3, "alpha": 2.5, "corr_threshold": 0.5}

    def make(self, n):
        return Anticor(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
