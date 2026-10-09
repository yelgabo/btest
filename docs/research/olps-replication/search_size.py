"""Counts the configurations run on 2016-2024 before the 1999-2024 work, from the saved outputs
(the working paper's Discussion). A configuration is one strategy result printed with a CAGR."""
import re
from pathlib import Path

OUT = Path(__file__).parent / "outputs"


def table_cells(name: str, skip_columns: int = 0) -> int:
    """CAGR cells in the strategy table of an output, leaving out the first skip_columns."""
    n = 0
    for line in (OUT / name).read_text().splitlines():
        cells = re.findall(r"-?\d+\.\d+% +-?\d\.\d\d +\d+x", line)
        if cells and not line.startswith(("CRP", "SPY")):
            n += len(cells[skip_columns:])
    return n


first = table_cells("monthly.out")
weekly = table_cells("weekly.out", skip_columns=1)
week_offsets = sum(int(m) for m in re.findall(r"every 5 sessions, (\d+) offsets",
                                               (OUT / "weekly.out").read_text()))
month_offsets = sum(int(m) for m in re.findall(r"every 21 sessions, (\d+) offsets",
                                               (OUT / "monthly_robustness.out").read_text()))
print(f"first search {first}; weekly trading or bars {weekly}; week-end offsets {week_offsets}; "
      f"monthly trading-day offsets {month_offsets}; total {first + weekly + week_offsets + month_offsets}")
