import numpy as np

from btest.strategy import Strategy


def realized_vol(close: np.ndarray, n: int, per_year: int = 252) -> np.ndarray:
    """Annualized standard deviation of the last n log returns at each bar."""
    out = np.full(len(close), np.nan)
    r = np.diff(np.log(close))
    for i in range(n, len(close)):
        out[i] = r[i - n:i].std() * np.sqrt(per_year)
    return out


def target_weights(vol: np.ndarray, target: float, cap: float, band: float) -> np.ndarray:
    """Weight that would give the target volatility, capped, but only re-issued once it has
    moved more than band away from the last weight ordered. NaN means keep the last order."""
    w = np.full(len(vol), np.nan)
    last = 0.0
    for i, v in enumerate(vol):
        if np.isnan(v) or v <= 0:
            continue
        want = min(cap, target / v)
        if abs(want - last) > band:
            w[i] = want
            last = want
    return w


class VolTarget(Strategy):
    """Always in the market, sized so the position's volatility stays near target_vol: smaller
    when markets are turbulent, up to max_weight when calm. Rebalances only when the ideal
    weight drifts more than rebalance_band from the last one, to keep trading down."""

    timeframe = "1D"
    params = {"symbol": "SPY", "target_vol": 0.15, "lookback": 20, "max_weight": 1.0,
              "rebalance_band": 0.1}

    def validate(self):
        p = self.params
        if p["lookback"] < 2 or p["target_vol"] <= 0 or not 0 < p["max_weight"] <= 1:
            raise ValueError("need lookback >= 2, target_vol > 0, 0 < max_weight <= 1")

    def on_start(self, ctx):
        self.last = 0.0

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        closes = ctx.history(bar.symbol, "close", p["lookback"] + 1)
        if len(closes) < p["lookback"] + 1:
            return
        v = realized_vol(closes, p["lookback"])[-1]
        if np.isnan(v) or v <= 0:
            return
        want = min(p["max_weight"], p["target_vol"] / v)
        if abs(want - self.last) > p["rebalance_band"]:
            ctx.order_target_percent(bar.symbol, want)
            self.last = want

    def signals(self, a):
        p = self.params
        vol = realized_vol(a["close"], p["lookback"])
        return target_weights(vol, p["target_vol"], p["max_weight"], p["rebalance_band"])
