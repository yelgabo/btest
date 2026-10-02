import numpy as np

from btest.indicator import Indicator


class SessionVWAP(Indicator):
    """Volume-weighted average price, restarting each trading day."""

    params = {}
    pane = "price"

    def compute(self, c):
        typical = (c["high"] + c["low"] + c["close"]) / 3
        # Shifting UTC back 4 hours lands every regular-session bar on its New York date in both
        # summer and winter time, since the session never crosses midnight.
        day = (c["t"] - 4 * 3600) // 86400
        vwap = np.full(len(typical), np.nan)
        pv = vol = 0.0
        for i in range(len(typical)):
            if i == 0 or day[i] != day[i - 1]:
                pv = vol = 0.0
            pv += typical[i] * c["volume"][i]
            vol += c["volume"][i]
            if vol > 0:
                vwap[i] = pv / vol
        return {"vwap": vwap}
