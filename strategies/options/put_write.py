from btest.portfolio import Targets
from btest.strategy import Strategy


class PutWrite(Strategy):
    """Sells cash-secured puts on one ETF, one monthly expiry at a time. When nothing is open
    it writes the put whose strike is closest to moneyness x price on the first monthly expiry
    at least min_days away, as many contracts as allocation of the cash secures. If a put is
    assigned, the shares are sold at the next decision and the cycle starts again."""

    universe = ["XLF"]
    rebalance = "daily"
    params = {"underlying": "XLF", "moneyness": 0.97, "min_days": 20, "allocation": 1.0,
              "min_volume": 1}

    def validate(self):
        p = self.params
        if not 0.5 <= p["moneyness"] <= 1.2 or not 0 < p["allocation"] <= 1:
            raise ValueError("moneyness must be in [0.5, 1.2] and allocation in (0, 1]")

    def decide(self, as_of, data):
        p = self.params
        u = p["underlying"]
        if data.option_positions():
            return None
        if data.position(u):
            return Targets(weights={})
        price = data.price(u)
        expiries = [e for e in data.expiries(u) if (e - data.today).days >= p["min_days"]]
        if price is None or not expiries:
            return None
        chain = data.option_chain(u, expiries[0], "P")
        chain = chain.filter(chain["volume"] >= p["min_volume"]) if p["min_volume"] else chain
        if chain.is_empty():
            return None
        target = p["moneyness"] * price
        row = chain.with_columns((chain["strike"] - target).abs().alias("gap")).sort("gap").row(
            0, named=True)
        contracts = int(data.cash * p["allocation"] // (row["strike"] * 100))
        if contracts < 1:
            data.report("skipped", f"{row['symbol']} needs ${row['strike'] * 100:,.0f} of cash")
            return None
        return Targets(options={row["symbol"]: -contracts})
