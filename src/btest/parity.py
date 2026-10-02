from dataclasses import dataclass

import polars as pl

from btest.engine import Config, Engine
from btest.fast import Prepared, run_fast
from btest.sources.base import Dividend, Split
from btest.strategy import Strategy


@dataclass
class ParityReport:
    event_fills: int
    fast_fills: int
    first_mismatch: int | None
    event_fill: tuple | None
    fast_fill: tuple | None
    max_equity_diff: float

    @property
    def ok(self) -> bool:
        return self.first_mismatch is None and self.max_equity_diff < 1e-6


def compare(cls: type[Strategy], params: dict, symbol: str, bars: pl.DataFrame,
            splits: list[Split], dividends: list[Dividend], config: Config) -> ParityReport:
    """Run both paths on the same bars. Any difference in fills means signals() and on_bar()
    disagree, most often because signals() reads a value from a later bar."""
    event = Engine({symbol: bars}, config, {symbol: splits}, {symbol: dividends}).run(cls(**params))
    prep = Prepared(bars, splits, dividends)
    fast = run_fast(prep, cls(**params).signals(prep.arrays), config)
    ts = prep.arrays["ts"]
    ev = [(f.ts, f.qty, round(f.price, 9)) for f in event.fills]
    fa = [(ts[b].item(), int(q), round(float(p), 9))
          for b, q, p in zip(fast.fill_bar, fast.fill_qty, fast.fill_price)]
    ev = [(t.replace(tzinfo=None), q, p) for t, q, p in ev]
    first = next((i for i, (a, b) in enumerate(zip(ev, fa)) if a != b), None)
    if first is None and len(ev) != len(fa):
        first = min(len(ev), len(fa))
    diff = (event.equity["equity"] - fast.equity["equity"]).abs().max() \
        if event.equity.height == fast.equity.height else float("inf")
    return ParityReport(
        len(ev), len(fa), first,
        ev[first] if first is not None and first < len(ev) else None,
        fa[first] if first is not None and first < len(fa) else None,
        float(diff or 0.0),
    )
