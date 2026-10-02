from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from btest.strategy import Strategy

NY = ZoneInfo("America/New_York")


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


def decide(ny_min, day, high, low, close, p):
    """One pass over the bars: target weight where the strategy acts, NaN elsewhere. Shared by
    on_bar (on the history so far) and signals (on everything) so both agree exactly."""
    w = np.full(len(close), np.nan)
    open_at, range_end, exit_at = 9 * 60 + 30, 9 * 60 + 30 + p["range_minutes"], hhmm(p["exit_at"])
    holding = traded = False
    or_high = or_low = None
    for i in range(len(close)):
        if i == 0 or day[i] != day[i - 1]:
            or_high = or_low = None
            traded = False
            if holding:
                # Still long from yesterday (a half day closes before exit_at): get out now.
                # The bar still counts toward today's opening range.
                w[i], holding = 0.0, False
        m = ny_min[i]
        if open_at <= m < range_end:
            or_high = high[i] if or_high is None else max(or_high, high[i])
            or_low = low[i] if or_low is None else min(or_low, low[i])
            continue
        if or_high is None:
            continue
        if holding:
            if m >= exit_at or (p["stop_at_range_low"] and close[i] < or_low):
                w[i], holding = 0.0, False
        elif not traded and m < exit_at and close[i] > or_high:
            w[i], holding, traded = p["allocation"], True, True
    return w


class OpeningRangeBreakout(Strategy):
    """Day trade: record the high and low of the first range_minutes after the 9:30 open, buy
    once if a bar closes above that high, sell at exit_at (New York time) or, if
    stop_at_range_low, when a bar closes below the range low. Never holds overnight except on
    half days, where it sells at the next open."""

    timeframe = "5m"
    params = {"symbol": "SPY", "range_minutes": 30, "exit_at": "15:50",
              "stop_at_range_low": True, "allocation": 1.0}

    def validate(self):
        p = self.params
        if p["range_minutes"] < 5 or not 9 * 60 + 30 < hhmm(p["exit_at"]) <= 16 * 60:
            raise ValueError("range_minutes >= 5 and exit_at between 09:30 and 16:00")

    def on_start(self, ctx):
        self.ts, self.day = [], []

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        self.ts.append(np.datetime64(bar.ts.replace(tzinfo=None), "us"))
        self.day.append(np.datetime64(bar.date, "D"))
        # Decisions only look back within today, so replaying today's bars is enough.
        start = len(self.day) - 1
        while start > 0 and self.day[start - 1] == self.day[-1]:
            start -= 1
        prev_day_end = max(0, start - 1)
        ts = np.array(self.ts[prev_day_end:])
        day = np.array(self.day[prev_day_end:])
        n = len(ts)
        high = ctx.history(bar.symbol, "high", n)
        low = ctx.history(bar.symbol, "low", n)
        close = ctx.history(bar.symbol, "close", n)
        held_overnight = start > 0 and ctx.position(bar.symbol) > 0 and start == len(self.day) - 1
        w = decide(ny_minutes(ts, day), day, high, low, close, p)
        want = w[-1]
        if held_overnight:
            want = 0.0
        if not np.isnan(want):
            ctx.order_target_percent(bar.symbol, want)

    def signals(self, a):
        day = a["date"].astype("datetime64[D]")
        return decide(ny_minutes(a["ts"], day), day, a["high"], a["low"], a["close"], self.params)
