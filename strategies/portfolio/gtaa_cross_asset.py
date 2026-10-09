from btest.strategy import Strategy

BROAD = ("SPY", "QQQ", "IWM", "TLT", "IEF", "HYG")


class GTAACrossAsset(Strategy):
    """Trend filter on 15 cross-asset ETFs (Faber's GTAA rule): at each month end, hold 1/15 of
    the account in every fund whose month-end close is above the average of its last 10
    month-end closes, and keep the other slices in cash at the T-bill rate. A fund without 10
    month-ends of history stays in cash. On long history it decides on the month's last close
    and fills at the next open; on minute bars it decides at 15:30 on the month's last session
    and fills at 15:45. Costs
    follow the schedule of olps/cwmr_weekly_open; universe and schedule are copied there and
    in the other cross-asset strategies, so keep them the same."""

    universe = ["SPY", "QQQ", "IWM", "SMH", "XBI", "KRE", "XME", "TLT", "IEF", "HYG", "GLD",
                "USO", "DBA", "FXI", "EWJ"]
    rebalance = "month_end"
    data = ("longhist", "btest")
    slippage_schedule = [
        (1999, 2002, [], 5.0),
        (2003, 2012, [], 2.5),
        (2013, 2024, list(BROAD), 1.0),
        (2013, 2024, [], 2.0),
    ]
    params = {"months": 10}

    def decide(self, as_of, data):
        months = self.params["months"]
        frame = data.frame("close")
        keys = [(d.year, d.month) for d in frame["date"].to_list()]
        ends = [i for i in range(len(keys)) if i == len(keys) - 1 or keys[i + 1] != keys[i]]
        want = {}
        for s in self.universe:
            col = frame[s].to_list()
            closes = [col[i] for i in ends[-months:]]
            if len(closes) == months and None not in closes and closes[-1] > sum(closes) / months:
                want[s] = 1.0 / len(self.universe)
        return want
