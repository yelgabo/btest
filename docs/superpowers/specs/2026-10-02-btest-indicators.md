# btest custom indicators

Status: shipped 2026-10-02.

## Job

Write indicators in Python in the website editor, version them like strategies, and add them to
any price chart next to the built-in SMA / EMA / Bollinger.

## Shape of an indicator

```python
import numpy as np
from btest.indicator import Indicator

class RSI(Indicator):
    params = {"length": 14}
    pane = "own"          # "price" draws on the candles, "own" gets a pane below
    levels = [30, 70]     # optional horizontal guide lines

    def compute(self, c):  # c: open, high, low, close, volume arrays (+ t)
        ...
        return {"rsi": values}   # one or more lines, each as long as the candles
```

## How it runs

| Step | Where |
|---|---|
| Stored as `lab.strategy` rows with `kind = 'indicator'`, versioned like strategies | Postgres |
| Chart asks `/api/indicators/:id/series?version&symbol&tf&start&end&params` | web |
| Web reads the code and forwards to the worker's private service (or computes locally in dev) | web |
| Worker loads candles for the range plus warm-up bars before it, starts a child process, sends code + candles on stdin | worker |
| Child has no database URL and no secrets, a 20 s limit, the same memory watch as runs; returns the lines or an error with its line number | child |
| Worker trims the warm-up and returns lines aligned to the candles | worker |

Warm-up: the worker loads 3 x the largest integer param + 10 candles before the range, so a
14-bar RSI on a chunk starts with real values instead of a gap. EMA-style indicators with
unbounded memory are close but not identical to a computation over all history.

## UI

- Explorer has two sections, Strategies and Indicators; Cmd+P searches both.
- Opening an indicator shows a Preview chart in place of the Run panel; Cmd+Enter saves and
  redraws it. Errors highlight the line.
- Every chart's "Add indicator" menu lists the custom indicators; their params become inputs on
  the chip.
