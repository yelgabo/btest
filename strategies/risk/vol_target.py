import numpy as np

from btest.strategy import Strategy


def realized_vol(close: np.ndarray, n: int, per_year: int = 252) -> np.ndarray:
    """Annualized standard deviation of the last n log returns at each bar."""
    out = np.full(len(close), np.nan)
    r = np.diff(np.log(close))
    for i in range(n, len(close)):
        out[i] = r[i - n:i].std() * np.sqrt(per_year)
    return out


def decide(last: float, vol: float, fast_vol: float, target: float, cap: float,
           band: float) -> float | None:
    """New weight to order, or None. Cuts follow the main window; adding back may follow the
    faster window, so exposure returns once recent volatility calms instead of waiting for the
    main window to forget the spike."""
    down = min(cap, target / vol)
    up = max(down, min(cap, target / fast_vol))
    if up - last > band:
        return up
    if last - down > band:
        return down
    return None


def target_weights(vol: np.ndarray, fast_vol: np.ndarray, target: float, cap: float,
                   band: float) -> np.ndarray:
    """Weights to order at each bar under decide(); NaN means keep the last order."""
    w = np.full(len(vol), np.nan)
    last = 0.0
    for i in range(len(vol)):
        if np.isnan(vol[i]) or vol[i] <= 0 or np.isnan(fast_vol[i]) or fast_vol[i] <= 0:
            continue
        want = decide(last, vol[i], fast_vol[i], target, cap, band)
        if want is not None:
            w[i] = want
            last = want
    return w


class VolTarget(Strategy):
    """Always in the market, sized so the position's volatility stays near target_vol: smaller
    when markets are turbulent, up to max_weight when calm. Rebalances only when the ideal
    weight drifts more than rebalance_band from the last one, to keep trading down.
    reentry_lookback lets exposure come back on a shorter volatility window after a spike; at or
    above lookback it behaves exactly like plain vol targeting."""

    timeframe = "1D"
    params = {"symbol": "SPY", "target_vol": 0.15, "lookback": 20, "reentry_lookback": 20,
              "max_weight": 1.0, "rebalance_band": 0.1}

    def validate(self):
        p = self.params
        if p["lookback"] < 2 or p["target_vol"] <= 0 or not 0 < p["max_weight"] <= 1:
            raise ValueError("need lookback >= 2, target_vol > 0, 0 < max_weight <= 1")
        if p["reentry_lookback"] < 2:
            raise ValueError("need reentry_lookback >= 2")

    def _fast_window(self):
        # Never slower than the main window: at or above lookback this is plain vol targeting.
        return min(self.params["reentry_lookback"], self.params["lookback"])

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
        fast = realized_vol(closes, self._fast_window())[-1]
        if np.isnan(v) or v <= 0 or np.isnan(fast) or fast <= 0:
            return
        want = decide(self.last, v, fast, p["target_vol"], p["max_weight"], p["rebalance_band"])
        if want is not None:
            ctx.order_target_percent(bar.symbol, want)
            self.last = want

    def signals(self, a):
        p = self.params
        vol = realized_vol(a["close"], p["lookback"])
        fast = realized_vol(a["close"], self._fast_window())
        return target_weights(vol, fast, p["target_vol"], p["max_weight"], p["rebalance_band"])
