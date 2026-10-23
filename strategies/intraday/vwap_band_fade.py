import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from btest.strategy import Strategy

NY = ZoneInfo("America/New_York")
OPEN = 9 * 60 + 30


def ny_minutes(ts: np.ndarray, day: np.ndarray) -> np.ndarray:
    """Minutes since midnight New York time for each bar, from UTC timestamps. The offset is
    looked up once per date, so summer and winter time are both right."""
    offsets = {}
    for d in np.unique(day):
        noon = datetime.combine(d.astype(datetime), datetime.min.time(), UTC) + timedelta(hours=17)
        offsets[d] = noon.astimezone(NY).utcoffset().total_seconds() / 60
    utc_min = (ts - day.astype("datetime64[us]")).astype("timedelta64[m]").astype(np.int64)
    return utc_min + np.array([offsets[d] for d in day], dtype=np.int64)


def hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


class Fader:
    """The trading rule as a state machine fed one bar at a time, so on_bar and signals run
    the same code and the event engine stays linear in the number of bars."""

    def __init__(self, p):
        self.p = p
        self.start_at, self.last_entry, self.exit_at = (
            hhmm(p["start_at"]), hhmm(p["last_entry"]), hhmm(p["exit_at"]))
        self.side = 0
        self.armed = True
        self.v = self.pv = self.pv2 = 0.0

    def step(self, m, new_day, high, low, close, volume):
        """Target weight after this bar closes, or NaN for no change."""
        p = self.p
        out = np.nan
        if new_day:
            self.v = self.pv = self.pv2 = 0.0
            self.armed = True
            if self.side:
                # Still holding from a half day (13:00 close, before exit_at): flatten at once.
                out, self.side = 0.0, 0
        if m < OPEN:
            return out
        tp = (high + low + close) / 3
        self.v += volume
        self.pv += tp * volume
        self.pv2 += tp * tp * volume
        if self.v <= 0:
            return out
        vwap = self.pv / self.v
        sd = math.sqrt(max(self.pv2 / self.v - vwap * vwap, 0.0))
        if sd == 0:
            return out
        z = (close - vwap) / sd
        if self.side:
            # -side * z is how far price has run against the position, in band widths.
            against = -self.side * z
            if m >= self.exit_at or against <= -p["exit_sd"] or against >= p["stop_sd"]:
                out, self.side, self.armed = 0.0, 0, abs(z) < p["entry_sd"]
            return out
        if not self.armed:
            self.armed = abs(z) < p["entry_sd"]
            return out
        if not self.start_at <= m <= self.last_entry:
            return out
        if z >= p["entry_sd"] and p["sides"] in ("both", "short"):
            out, self.side = -p["allocation"], -1
        elif z <= -p["entry_sd"] and p["sides"] in ("both", "long"):
            out, self.side = p["allocation"], 1
        return out


class VWAPBandFade(Strategy):
    """Day trade against stretches from the session VWAP. The bands are the volume-weighted
    standard deviation of the typical price around VWAP since the 9:30 open. A bar closing
    entry_sd bands above VWAP opens a short, entry_sd below opens a long. The position closes
    when price returns to exit_sd bands short of VWAP (0 means VWAP itself), when it runs to
    stop_sd bands, or at exit_at. After an exit, price must come back inside the entry band
    before the next entry. Needs --allow-short for the short side."""

    timeframe = "1m"
    params = {"symbol": "SPY", "entry_sd": 2.0, "exit_sd": 0.0, "stop_sd": 3.0,
              "start_at": "10:00", "last_entry": "15:30", "exit_at": "15:50",
              "sides": "both", "allocation": 1.0}

    def validate(self):
        p = self.params
        if not 0 <= p["exit_sd"] < p["entry_sd"] < p["stop_sd"]:
            raise ValueError("need 0 <= exit_sd < entry_sd < stop_sd")
        if p["sides"] not in ("both", "long", "short"):
            raise ValueError("sides is both, long or short")
        # The exit is decided at the close of the exit_at bar and fills at the next bar's
        # open, so 15:58 is the last exit that still fills before the 16:00 close.
        if not OPEN <= hhmm(p["start_at"]) <= hhmm(p["last_entry"]) < hhmm(p["exit_at"]) <= 15 * 60 + 58:
            raise ValueError("need 9:30 <= start_at <= last_entry < exit_at <= 15:58")

    def on_start(self, ctx):
        self.fader = Fader(self.params)
        self.prev_day = None

    def on_bar(self, ctx, bar):
        if bar.symbol != self.params["symbol"]:
            return
        local = bar.ts.astimezone(NY)
        m = local.hour * 60 + local.minute
        new_day = self.prev_day is not None and bar.date != self.prev_day
        self.prev_day = bar.date
        want = self.fader.step(m, new_day, bar.high, bar.low, bar.close, bar.volume)
        if not np.isnan(want):
            ctx.order_target_percent(bar.symbol, want)

    def signals(self, a):
        day = a["date"].astype("datetime64[D]")
        ny_min = ny_minutes(a["ts"], day)
        f = Fader(self.params)
        w = np.full(len(day), np.nan)
        for i in range(len(day)):
            w[i] = f.step(ny_min[i], i > 0 and day[i] != day[i - 1], a["high"][i], a["low"][i],
                          a["close"][i], a["volume"][i])
        return w
