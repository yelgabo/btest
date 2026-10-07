"""Online portfolio template: a portfolio strategy driven by an online learning algorithm.

An online algorithm keeps learned state and updates it one period at a time: it sees a row of
price ratios (each symbol's close divided by its previous close), changes its state, and says
what share of the account to hold in each symbol next. btest.olps has the published ones
(CWMRAuthors, PAMRAuthors, ExponentialGradient, Anticor, ...); OnlineStrategy runs any of them
as a decide() strategy.

As is, it runs and trades: a small mean-reversion rule that moves weight from the period's
winners to its losers. Replace the algorithm, or use one from btest.olps, then edit make().
"""

from btest.olps import Online, OnlineStrategy, project_to_simplex


class TiltToLosers(Online):
    """Each period, move weight from symbols that beat the period's average to those that
    trailed it: step times the gap, so step 0.5 and a 2% gap move 1% of the account."""

    def __init__(self, n, step=0.5):
        # self.b starts at equal weights, one entry per universe symbol.
        super().__init__(n)
        self.step = step

    def update(self, x):
        # x: this period's price ratios, one per symbol (1.02 = up 2%). A symbol not trading
        # yet gets the average ratio of those that are, so this rule leaves its weight alone;
        # OnlineStrategy spreads whatever weight it has equally across the trading symbols.
        tilt = self.step * (x.mean() - x)
        self.b = project_to_simplex(self.b + tilt)

    # portfolio() returns self.b: weights >= 0 that add up to 1. Override it if the algorithm
    # keeps something other than b.


class MyOnlinePortfolio(OnlineStrategy):
    """One line on the idea, then the rules in plain words."""

    # Symbols the algorithm chooses between. A symbol joins on its first trading day; until
    # then it holds nothing and the algorithm keeps what it has learned about the others.
    universe = ["SPY", "QQQ", "IWM", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLP", "XLU"]

    # Which sessions decide() is called on: "daily", "weekly" (last session of the week),
    # "month_end" or "month_start".
    rebalance = "weekly"

    # What one row of price ratios covers: "daily" (every session, also between decisions),
    # "weekly" (week-end closes) or "monthly" (month-end closes). Pair "weekly" with
    # rebalance = "weekly" and "monthly" with "month_end" to judge winners and losers over the
    # same period the strategy holds.
    bars = "weekly"

    # Tunable inputs, passed to the algorithm in make() and editable in the Run panel.
    params = {"step": 0.5}

    def validate(self):
        if not 0 < self.params["step"] <= 10:
            raise ValueError("step must be above 0 and at most 10")

    # -------------------------------------------------------------------------------------
    # make(n) builds a fresh algorithm for n symbols (n = len(universe)). At each decision
    # OnlineStrategy feeds it every completed bar since the data starts, then today's prices
    # at the cutoff, and holds what portfolio() returns. Within a run it keeps the algorithm
    # between decisions and only feeds new bars; a fresh process (the live system) replays
    # the whole history and reaches the same state.
    #
    # Timing depends on the run's Data choice:
    #   btest bars (from 2016)  decides at 15:30 New York time on data through 15:14; orders
    #                           fill at 15:45
    #   long history (1995)     decides on each session's close; orders fill at the next
    #                           session's open
    # Prices are split- and dividend-adjusted, so a ratio is a total return.
    # -------------------------------------------------------------------------------------
    def make(self, n):
        return TiltToLosers(n, **self.params)

    def decide(self, as_of, data):
        return self.run_online(data)
