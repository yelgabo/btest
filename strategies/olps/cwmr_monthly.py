from btest.olps import CWMRAuthors, OnlineStrategy


class CWMRMonthly(OnlineStrategy):
    """The NYU paper's CWMR variant, learning from daily prices but trading only at each month
    end. Daily, it holds one ETF most days and trades about 350x its value a year; monthly, it
    trades about 18x. On these 16 ETFs, 2016-2024, at 0.7 bp: 18.3% a year against SPY's 13.8%,
    and 18 of 21 alternative trading days also beat SPY (docs/research/olps-replication/
    outputs/monthly_robustness.out). Not statistically significant (paired p 0.27), and chosen
    as the best of about 26 variants tried, so treat it as a hypothesis for the holdout."""

    universe = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI",
                "XLY", "XLP", "XLU", "XLB", "XLRE"]
    rebalance = "month_end"
    params = {"epsilon": 0.89, "theta": 0.92, "eta": 0.93}

    def make(self, n):
        return CWMRAuthors(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
