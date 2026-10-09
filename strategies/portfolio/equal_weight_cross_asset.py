from btest.strategy import Strategy

BROAD = ("SPY", "QQQ", "IWM", "TLT", "IEF", "HYG")


class EqualWeightCrossAsset(Strategy):
    """Equal weight in the 15 cross-asset ETFs that have started trading, reset at each month
    end; the benchmark for portfolio/gtaa_cross_asset and risk/inverse_vol_cross_asset, on the
    same timing (decide on the close, fill at the next open) and costs (universe and schedule
    copied from olps/cwmr_weekly_open, keep them the same)."""

    universe = ["SPY", "QQQ", "IWM", "SMH", "XBI", "KRE", "XME", "TLT", "IEF", "HYG", "GLD",
                "USO", "DBA", "FXI", "EWJ"]
    rebalance = "month_end"
    data = "longhist"
    slippage_schedule = [
        (1999, 2002, [], 5.0),
        (2003, 2012, [], 2.5),
        (2013, 2024, list(BROAD), 1.0),
        (2013, 2024, [], 2.0),
    ]
    params = {}

    def decide(self, as_of, data):
        live = [s for s in self.universe if len(data.history(s, "close", 2)) == 2]
        return {s: 1.0 / len(live) for s in live} if live else None
