import numpy as np

from btest.strategy import Strategy


def wilder_rsi(close: np.ndarray, n: int) -> np.ndarray:
    """RSI with Wilder's smoothing, NaN for the first n bars."""
    rsi = np.full(len(close), np.nan)
    if len(close) <= n:
        return rsi
    delta = np.diff(close, prepend=close[0])
    gain, loss = np.clip(delta, 0, None), np.clip(-delta, 0, None)
    avg_gain, avg_loss = gain[1:n + 1].mean(), loss[1:n + 1].mean()
    for i in range(n, len(close)):
        if i > n:
            avg_gain = (avg_gain * (n - 1) + gain[i]) / n
            avg_loss = (avg_loss * (n - 1) + loss[i]) / n
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


def sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


class RSI2Pullback(Strategy):
    """Larry Connors' RSI(2): in an uptrend (close above its trend_ma-day average), buy when
    the short RSI drops below entry, sell when the close gets back above its exit_ma-day
    average. Long only, daily bars."""

    timeframe = "1D"
    params = {"symbol": "SPY", "rsi_length": 2, "entry": 10.0, "exit_ma": 5, "trend_ma": 200,
              "allocation": 1.0}

    def validate(self):
        p = self.params
        if p["rsi_length"] < 1 or p["exit_ma"] < 1 or p["trend_ma"] < 1 or not 0 < p["entry"] < 100:
            raise ValueError("lengths must be >= 1 and 0 < entry < 100")

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        # RSI is recursive, so it reads the whole history to match signals() exactly.
        closes = ctx.history(bar.symbol, "close")
        need = max(p["trend_ma"], p["exit_ma"], p["rsi_length"] + 1)
        if len(closes) < need:
            return
        rsi = wilder_rsi(closes, p["rsi_length"])[-1]
        trend, exit_ma = sma(closes, p["trend_ma"])[-1], sma(closes, p["exit_ma"])[-1]
        holding = ctx.position(bar.symbol) > 0
        if not holding and rsi < p["entry"] and bar.close > trend:
            ctx.order_target_percent(bar.symbol, p["allocation"])
        elif holding and bar.close > exit_ma:
            ctx.order_target(bar.symbol, 0)

    def signals(self, a):
        p = self.params
        c = a["close"]
        rsi = wilder_rsi(c, p["rsi_length"])
        trend, exit_ma = sma(c, p["trend_ma"]), sma(c, p["exit_ma"])
        w = np.full(len(c), np.nan)
        holding = False
        for i in range(len(c)):
            if np.isnan(trend[i]) or np.isnan(exit_ma[i]) or np.isnan(rsi[i]):
                continue
            if not holding and rsi[i] < p["entry"] and c[i] > trend[i]:
                w[i], holding = p["allocation"], True
            elif holding and c[i] > exit_ma[i]:
                w[i], holding = 0.0, False
        return w
