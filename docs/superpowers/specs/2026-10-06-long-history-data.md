# Long-history data in btest

Goal: run portfolio strategies from the website on 1995 onward.

## Shape

- **A second data source, chosen per run**, because the bars are a different resolution. btest's
  store holds Alpaca minute bars from 2016; this holds Yahoo day bars from 1995. Day bars cannot
  supply the 15:14 cutoff price and 15:45 fill the minute store is built around, so the two are
  not merged. Minute bars from any vendor would go into the main store instead.
- Run config gains `data`: `"btest"` (default) or `"longhist"`.
- **Each symbol is only itself**, from its first trading day: QQQ from 1999-03-10, the sector
  SPDRs from 1998-12-22. Nothing is spliced in before a launch. A strategy's universe grows as
  symbols start trading; `OnlineStrategy` keeps its learned state when one joins.
- **Storage in Postgres**, table `market.longhist (symbol, date, close)`. Lab jobs run on the
  Railway worker, which shares the database but not the local data volume.
- **Loader `btest longhist`** downloads every symbol in `btest.toml` (Yahoo adjusted closes,
  dividends and splits included) and FRED DTB3 back to 1995, and replaces the table. Run by hand.
- **Timing:** the strategy decides on each session's close and fills at it.
- **Sessions:** the NYSE calendar from `pandas_market_calendars`.

## Not included

- Event-engine strategies (`on_bar`) and sweeps: they need minute bars.
- Options.

## History

The first version (commit cf7de98) spliced stand-in funds and indexes under ETF names before
each launch, as the 1995-2015 research test had. Replaced: a symbol is only ever itself. The
research test in `docs/research/olps-replication/long_history.py` keeps its stand-in data as
the record of what was pre-registered; runs 74-77 used it.

## Checks

- Unit tests: each symbol starts on its first day; frames built from stored rows;
  `validate_spec` accepts `longhist` with a 1995 start and refuses sweeps and on_bar strategies.
- A website run of monthly CWMR on long history completes and labels itself as such.
