# Long-history data in btest

Goal: run portfolio strategies from the website on 1995 onward, using the spliced ETF and
stand-in fund series that `docs/research/olps-replication/long_history.py` built for the
1995-2015 CWMR test.

## Shape

- **A second data source, chosen per run.** Run config gains `data`: `"btest"` (default; the
  Alpaca minute bars from 2016) or `"longhist"`. Symbols keep their ETF names, so a strategy's
  `universe` works unchanged; only where the prices come from differs.
- **Storage in Postgres**, table `market.longhist (symbol, date, close, source)`. Lab jobs run on
  the Railway worker, which shares the database but not the local data volume. `source` names
  the fund or ETF that supplied each day's return (`RYOCX` before 1999-03-10, `QQQ` after).
- **Loader `btest longhist`** downloads the series (Yahoo adjusted closes, Ken French 12-industry
  daily file, FRED DTB3 back to 1995) and replaces the table. Run by hand when fresher data is
  wanted; the worker does not refresh it.
- **Symbols:** the 16 OLPS ETFs plus AGG, whose stand-in is Vanguard Total Bond Market Index
  (VBMFX), so the 60/40 benchmark works. Any other symbol is refused with the list.
- **Timing:** daily closes only, so the strategy decides on each session's close and fills at it
  (btest's own data decides at 15:30 and fills at 15:45). No splits or dividends: adjusted closes
  already include them.
- **Sessions:** the NYSE calendar from `pandas_market_calendars` (`market.session` starts 2016 and
  stays as it is, because the bar cache builds one row per session in it).

## Not included

- Event-engine strategies (`on_bar`) and sweeps: they need minute bars.
- Options: none before 2016.
- The research script stays as it is; it is the record of the pre-registered test and reads its
  own cached files.

## Checks

- Unit tests: frames built from stored rows; `validate_spec` accepts `longhist` symbols and a
  1995 start and refuses others.
- Same numbers as the research script: monthly CWMR 1995-2015 at 0.7 bp gives 11.57% and SPY
  9.33% (run 74), here run from the website after deploying.
