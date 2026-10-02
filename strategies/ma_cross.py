from btest.strategy import Strategy


class MovingAverageCross(Strategy):
    """Long when the fast moving average of adjusted close is above the slow one, flat
    otherwise. Windows are in minute bars (390 per regular session)."""

    params = {"fast": 30, "slow": 390, "symbol": "SPY", "allocation": 1.0}

    def on_bar(self, ctx, bar):
        p = self.params
        if bar.symbol != p["symbol"]:
            return
        closes = ctx.history(bar.symbol, "close", p["slow"])
        if len(closes) < p["slow"]:
            return
        fast = closes[-p["fast"]:].mean()
        slow = closes.mean()
        holding = ctx.position(bar.symbol) > 0
        if fast > slow and not holding:
            ctx.order_target_percent(bar.symbol, p["allocation"])
        elif fast < slow and holding:
            ctx.order_target(bar.symbol, 0)
