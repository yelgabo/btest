from btest.olps import OnlineStrategy, MetaExperts


class MetaNewtonStrategy(OnlineStrategy):
    """Ensemble of CWMR, PAMR, RMR and OLMAR (the paper's versions) with an online Newton step on
    the expert weights: the NYU paper's online Newton update (56.8x). Each expert keeps running
    from day to day instead of being re-run over the whole history every step."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "daily"
    params = {"method": "newton", "learning_rate": 0.01,
              "experts": ["cwmr", "pamr", "rmr", "olmar"]}

    def make(self, n):
        return MetaExperts(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
