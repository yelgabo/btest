import numpy as np

from btest.strategy import Strategy

BROAD = ("SPY", "QQQ", "IWM", "TLT", "IEF", "HYG")


class InverseVolCrossAsset(Strategy):
    """Inverse-volatility weights on 15 cross-asset ETFs: at each month end, weight every fund
    by one over the standard deviation of its last 60 daily returns, normalised to sum to one.
    Funds without 60 returns of history are left out. No volatility target or leverage. Decides
    on the close, fills at the next open; costs as in olps/cwmr_weekly_open (universe and
    schedule copied, keep them the same)."""

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
    params = {"days": 60}

    def decide(self, as_of, data):
        inverse = {}
        for s in self.universe:
            close = data.history(s, "close", self.params["days"] + 1)
            if len(close) == self.params["days"] + 1:
                sd = np.std(close[1:] / close[:-1] - 1, ddof=1)
                if sd > 0:
                    inverse[s] = 1.0 / sd
        total = sum(inverse.values())
        return {s: v / total for s, v in inverse.items()} if inverse else None
