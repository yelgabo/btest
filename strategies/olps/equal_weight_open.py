from btest.strategy import Strategy

BROAD = ("SPY", "QQQ", "IWM", "TLT", "IEF", "HYG")


class EqualWeightOpen(Strategy):
    """Equal weight in the 15 ETFs of olps/cwmr_weekly_open, reset at each month end, on the
    same timing (on long history, decide on the open and fill at that session's close; on minute
    bars, decide at 15:30 and fill at 15:45) and the same cost schedule,
    so the two compare like for like. Lab strategies are single files, so the universe and
    schedule are copied here; keep them the same as cwmr_weekly_open's."""

    universe = ["SPY", "QQQ", "IWM", "SMH", "XBI", "KRE", "XME", "TLT", "IEF", "HYG", "GLD",
                "USO", "DBA", "FXI", "EWJ"]
    rebalance = "daily"
    data = ("longhist_open", "btest")
    slippage_schedule = [
        (1999, 2002, [], 5.0),
        (2003, 2012, [], 2.5),
        (2013, 2024, list(BROAD), 1.0),
        (2013, 2024, [], 2.0),
    ]
    params = {}

    def decide(self, as_of, data):
        if data.month_position()[1] != 1 and data.positions():
            return None
        live = [s for s in data.symbols if len(data.history(s, "close", 2)) == 2]
        return {s: 1.0 / len(live) for s in live} if live else None
