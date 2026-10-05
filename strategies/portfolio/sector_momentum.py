from btest.strategy import Strategy


class SectorMomentum(Strategy):
    """Holds the strongest sector ETFs by return over the lookback, equal weight, rebalanced at
    each month end. With trend_filter on, goes to cash while SPY is below its moving average.
    Sectors without a full lookback of history (XLC before 2019) are left out."""

    universe = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
                "SPY"]
    rebalance = "month_end"
    params = {"top": 3, "lookback": 126, "trend_filter": True, "trend_days": 200}

    def validate(self):
        if self.params["top"] < 1 or self.params["lookback"] < 21:
            raise ValueError("top must be >= 1 and lookback >= 21")

    def decide(self, as_of, data):
        p = self.params
        if p["trend_filter"]:
            spy = data.history("SPY", "close", p["trend_days"])
            if len(spy) == p["trend_days"] and spy[-1] < spy.mean():
                return {}
        scores = {}
        for s in self.universe:
            if s == "SPY":
                continue
            close = data.history(s, "close", p["lookback"] + 1)
            if len(close) > p["lookback"]:
                scores[s] = close[-1] / close[0] - 1
        if not scores:
            return None
        top = sorted(scores, key=scores.get, reverse=True)[: p["top"]]
        return {s: 1.0 / len(top) for s in top}
