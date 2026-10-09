from btest.olps import CWMRAuthors, OnlineStrategy

BROAD = ("SPY", "QQQ", "IWM", "TLT", "IEF", "HYG")


class CWMRWeeklyOpen(OnlineStrategy):
    """The NYU paper's CWMR on a cross-asset set of 15 ETFs, learning from week-over-week price
    ratios measured open to open: each week's first session's open against the previous week's.
    It decides on that open and fills at the same session's close, the first price after the
    decision. Costs rise for earlier years and for narrower funds; the schedule is an assumption
    from outside estimates, not measured spreads. Funds join on their first trading day, so
    before 2004 the set is mostly SPY, QQQ, IWM and EWJ. Exploratory, chosen after the working
    paper's results; not pre-registered."""

    universe = ["SPY", "QQQ", "IWM", "SMH", "XBI", "KRE", "XME", "TLT", "IEF", "HYG", "GLD",
                "USO", "DBA", "FXI", "EWJ"]
    bars = "weekly"
    price = "open"
    anchor = "first"
    rebalance = "week_start"
    data = "longhist_open"
    # bps per dollar traded by year and fund; the first match wins.
    slippage_schedule = [
        (1999, 2002, [], 5.0),
        (2003, 2012, [], 2.5),
        (2013, 2024, list(BROAD), 1.0),
        (2013, 2024, [], 2.0),
    ]
    params = {"epsilon": 0.89, "theta": 0.92, "eta": 0.93}

    def make(self, n):
        return CWMRAuthors(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
