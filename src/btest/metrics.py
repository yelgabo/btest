import math

import polars as pl

TRADING_DAYS = 252


def compute(equity: pl.DataFrame, rf: pl.DataFrame | None = None) -> dict:
    """Metrics from a daily (date, equity) series. rf holds (date, rate) as annual percent,
    e.g. the 3-month T-bill yield. Returns start from the first row, the first session's close,
    for strategies and benchmarks alike, so trading during the first session is not counted."""
    eq = equity.sort("date")
    values = eq["equity"].to_list()
    if len(values) < 2 or values[0] <= 0:
        return {"days": len(values)}
    rets = eq.with_columns((pl.col("equity") / pl.col("equity").shift(1) - 1).alias("ret"))
    rets = rets.slice(1)
    if rf is not None and not rf.is_empty():
        rets = rets.sort("date").join_asof(rf.sort("date"), on="date", strategy="backward")
        rets = rets.with_columns((pl.col("rate").fill_null(0.0) / 100 / TRADING_DAYS).alias("rf"))
    else:
        rets = rets.with_columns(pl.lit(0.0).alias("rf"))
    excess = (rets["ret"] - rets["rf"])
    years = (eq["date"][-1] - eq["date"][0]).days / 365.25
    total = values[-1] / values[0] - 1
    std = rets["ret"].std()
    excess_std = excess.std()
    downside = math.sqrt((excess.clip(upper_bound=0) ** 2).mean())
    dd, dd_days = _drawdown(eq)
    return {
        "days": len(values),
        "start_equity": values[0],
        "end_equity": values[-1],
        "total_return": total,
        "cagr": (values[-1] / values[0]) ** (1 / years) - 1 if years > 0 and values[-1] > 0
                else None,
        "ann_vol": std * math.sqrt(TRADING_DAYS) if std else 0.0,
        "sharpe": excess.mean() / excess_std * math.sqrt(TRADING_DAYS) if excess_std else None,
        "sortino": excess.mean() / downside * math.sqrt(TRADING_DAYS) if downside else None,
        "max_drawdown": dd,
        "max_drawdown_days": dd_days,
    }


def _drawdown(eq: pl.DataFrame) -> tuple[float, int]:
    peak = peak_date = None
    worst = 0.0
    longest = 0
    for d, v in eq.select("date", "equity").iter_rows():
        if peak is None or v >= peak:
            peak, peak_date = v, d
        else:
            worst = min(worst, v / peak - 1)
            longest = max(longest, (d - peak_date).days)
    return worst, longest


def trade_stats(fills, equity: pl.DataFrame, multiplier=lambda symbol: 1) -> dict:
    """win_rate is per closing fill, so a position closed in three fills counts three times.
    turnover is buys plus sells over average equity, per year (twice the one-sided figure)."""
    closes = [f.realized_pnl for f in fills if f.realized_pnl is not None]
    traded = sum(abs(f.qty) * f.price * multiplier(f.symbol) for f in fills)
    avg_eq = equity["equity"].mean() if not equity.is_empty() else 0.0
    years = ((equity["date"][-1] - equity["date"][0]).days / 365.25
             if equity.height > 1 else 0.0)
    return {
        "fills": len(fills),
        "closing_fills": len(closes),
        "win_rate": sum(1 for p in closes if p > 0) / len(closes) if closes else None,
        "turnover": traded / avg_eq / years if avg_eq and years else None,
        "costs": sum(f.commission + f.fees + f.slippage for f in fills),
    }
