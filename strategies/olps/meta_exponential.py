from btest.olps import OnlineStrategy, MetaExperts


class MetaExponentialStrategy(OnlineStrategy):
    """Ensemble of CWMR, FTRL and PAMR reweighted each session by exp(-learning_rate * log loss).
    This is the NYU paper's fast universalization and online gradient update, which use the same
    rule (paper: 68x and 66x). Unlike the authors' code, each expert keeps running from day to
    day instead of being re-run over the whole history every step."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"method": "exponential", "learning_rate": 0.01,
              "experts": ["cwmr", "ftrl", "pamr"]}

    def make(self, n):
        return MetaExperts(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
