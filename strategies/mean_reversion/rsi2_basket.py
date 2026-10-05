import numpy as np

from btest.strategy import Strategy


def wilder_rsi_last(close: np.ndarray, n: int) -> float:
    """RSI with Wilder's smoothing at the last value; NaN with too little history."""
    if len(close) <= n:
        return float("nan")
    delta = np.diff(close)
    gain, loss = np.clip(delta, 0, None), np.clip(-delta, 0, None)
    avg_gain, avg_loss = gain[:n].mean(), loss[:n].mean()
    for up, down in zip(gain[n:], loss[n:]):
        avg_gain = (avg_gain * (n - 1) + up) / n
        avg_loss = (avg_loss * (n - 1) + down) / n
    return 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)


class RSI2Basket(Strategy):
    """Connors' RSI(2) pullback across index ETFs. Buys an ETF when its 2-day RSI drops below
    entry_rsi while it is above its long moving average, sells when it closes above its short
    moving average. Each ETF gets an equal slice; unused slices stay in cash."""

    universe = ["SPY", "QQQ", "IWM", "DIA"]
    rebalance = "daily"
    params = {"rsi_days": 2, "entry_rsi": 10.0, "trend_days": 200, "exit_days": 5,
              "rsi_warmup": 100}

    def decide(self, as_of, data):
        p = self.params
        slice_ = 1.0 / len(self.universe)
        held = data.positions()
        want = {}
        for s in self.universe:
            close = data.history(s, "close", max(p["trend_days"], p["rsi_warmup"]))
            if len(close) < p["trend_days"]:
                continue
            if s in held:
                if close[-1] <= close[-p["exit_days"]:].mean():
                    want[s] = slice_
            elif (close[-1] > close.mean()
                  and wilder_rsi_last(close[-p["rsi_warmup"]:], p["rsi_days"]) < p["entry_rsi"]):
                want[s] = slice_
        if set(want) == set(held):
            return None
        # Existing positions keep their size; only entries and exits trade.
        weights = data.weights()
        return {s: weights.get(s, w) for s, w in want.items()}
