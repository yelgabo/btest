"""btest's CWMR port (strategies/olps/cwmr.py) against the authors' cwmr() on the paper's data."""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORK = os.environ.get("OLPS_WORK", os.path.dirname(os.path.abspath(__file__)))
OLPS = os.environ.get("OLPS_REPO", os.path.join(WORK, "olps-repo"))
sys.path[:0] = [OLPS + "/Scripts", OLPS + "/Scripts/Strategies"]
import follow_the_loser as ftl  # noqa: E402
from btest.runner import load_strategy_class  # noqa: E402

port = load_strategy_class(Path("strategies/olps/cwmr.py"))()
rel = pd.read_csv(OLPS + "/Data/Price Relative Vectors/price_relative_vectors.csv", index_col=0).to_numpy(float)
n = rel.shape[1]
b0 = np.full(n, 1 / n)
theirs = np.asarray(ftl.cwmr(b0, rel))
mu, sig, worst = b0.copy(), np.eye(n), 0.0
for t in range(1, len(rel)):
    mu, sig = port._step(mu, sig, rel[t - 1])
    worst = max(worst, float(np.abs(mu - theirs[t]).max()))
print(f"largest weight difference, btest port vs authors' cwmr(), {len(rel) - 1} updates: {worst:.1e}")
