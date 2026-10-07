# Adversarial review: weekly-bars CWMR beats SPY

## Claim under review

"CWMR (the NYU paper's simplified Confidence-Weighted Mean Reversion), learning from week-end
closes and trading at each week end on 16 US equity ETFs, beats SPY: 13.32% against 8.09% a year
over 1999-2024 at 0.7 bp per dollar traded; all five week-end offsets beat SPY before 2016; it
passed a pre-registered 1999-2015 test." Intended use: the user may publish this as a finding.

## Snapshot

Repository `btest`, commit `48be40f` (clean tree). SHA-256 prefixes:

| File | SHA-256 (first 16) |
|---|---|
| docs/research/2026-10-04-online-portfolio-selection-paper.md | 81617005e4942605 |
| src/btest/olps.py | 2899b9b9fd4ffdab |
| src/btest/longhist.py | e24c163be351b00b |
| src/btest/runner.py | e7b15c948fcda520 |
| src/btest/portfolio.py | 23031609f16bd702 |
| strategies/olps/cwmr_weekly_bars.py | 39398bbc7f08d3ce |
| docs/research/olps-replication/bars_1999.py | c393459604b8d10f |
| docs/research/olps-replication/weekly_offsets_longhist.py | 04e4c5b6346f8c35 |
| docs/research/olps-replication/weekly.py | 396245a90267a5dd |

Evidence: research doc sections from "Holdout test of monthly CWMR" (line 294) to "Applications
for btest" (line 486); script outputs in `docs/research/olps-replication/outputs/`
(`weekly.out`, `bars_1999.out`, `weekly_offsets_longhist.out`); website runs 80-83 in
`runs.run` (80 monthly bars 1999-2015, 81 weekly bars 1999-2015, 82 weekly bars 1999-2024 at
0.7 bp, 83 the same at 10 bp). Data: `market.longhist`, Yahoo adjusted daily closes loaded
2026-10-06 by `btest longhist`.

## Panel

Four independent reviewers, run in parallel with the snapshot and evidence list and no expected
conclusions: a quantitative researcher and statistician, a data engineer and backtest code
auditor, a practitioner who has traded systematic ETF strategies, and a hostile reader checking
wording against sources. All four were read-only and ran nothing on data from 2025 on. Between
them they reproduced runs 81, 82 and 83, SPY's 8.09%, and every row of
`weekly_offsets_longhist.out`; the auditor also matched the stored data to a fresh Yahoo download
(ratio 1 within 3e-6 on every date) and wrote an independent CWMR that gives 13.315% and 5.575%.
Agreement among reviewers is not proof; the main findings below were rechecked against the data.

## Findings and dispositions

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | The strategy decides on a close and fills at that same close (`longhist.py`: every price column is the close). No one can trade at a close after seeing it. One session later, 1999-2024 falls from 13.3% to 9.8% and 1999-2015 from 11.5% to 7.3%; 2016-2024 roughly ties SPY (14.3-14.6% against 14.4%). | All four | **Confirmed defect.** Rechecked: same close 11.51% / 16.87% / 13.34%, next close 7.28% / 14.61% / 9.76% (1999-2015 / 2016-2024 / 1999-2024). A one-session delay overstates live slippage; btest's live 15:30 decision and 15:45 fill falls between. On 2016-2024 minute data the 15:45 version returned 17.6%, so the shortcut does not inflate that period; nothing measures it before 2016, where the lead comes from. The auditor found negative next-day reversal in pre-2016 closes (lag-1 autocorrelation of excess returns -0.05 to -0.09, 0.00 after 2016), consistent with bid-ask bounce in closing prints. |
| 2 | Costs: 0.7 bp is a 2016-2024 spread measurement applied from 1999. At 76x turnover each basis point costs about 0.8% a year; the break-even against SPY is about 7 bp over 1999-2024, and 3.7 bp over 2016-2024. Before April 2001 the $1/16 tick alone set a half-spread of 5-12 bp on sector SPDRs. | All four | **Confirmed defect** (break-even from runs 82 and 83; tick arithmetic is a lower bound, not a measurement). No sourced spread data for 1999-2005 was found. |
| 3 | No commissions. Run 82 makes 174-315 fills a year; at the 1999 average of $15.75 a trade (SEC report), that is about $4,700 a year, roughly a quarter of the $20,000 account. Commissions only reached zero in October 2019. | Practitioner | **Confirmed defect.** Rechecked fill counts: 243 (1999), 315 (2000), 283 (2001). The practitioner's era-by-era schedule wipes out a $20,000 account by 2009; at $1M the CAGR is 13.2%. |
| 4 | The pre-registered test was too easy: equal weight in the same ETFs also beats SPY over 1999-2015 (6.61%, Sharpe 0.33, against 4.90%, 0.25), which runs 78-79 had already shown before the pre-registration. Against equal weight the paired p is 0.09 (block bootstrap 0.045). | Quant, hostile reader | **Confirmed.** The pre-registration was committed before runs 80-81 (18:06:29 against 18:07:03), so it is genuine, but its benchmark could not separate the strategy from holding the ETFs. |
| 5 | In-sample and out-of-sample results are mixed in the claim: 13.32% covers 2016-2024, the period that selected the variant; only 1999-2015 was pre-registered. | All four | **Confirmed presentation defect.** |
| 6 | Multiple comparisons are undercounted: about 100 configurations across the research doc, four pre-registered tests (one failed, one passed only on stand-in data, one passed without beating equal weight). Bonferroni over the four tests turns p 0.022 into 0.09 (Memmel test) or 0.016 (block bootstrap). | Quant | **Confirmed** as a limitation; the count is the reviewer's and is approximate. |
| 7 | Concentration: "16 ETFs" is the choice set. The median portfolio holds 2; one fund 31% of weeks; largest weight 50% or more in 80% of weeks, 90% or more in 36%. | Practitioner | **Confirmed** (rechecked over 1,356 decisions). |
| 8 | Taxes: at 76x turnover almost all gains are short-term; estimated after-tax CAGR 8.8% at a 35% rate against SPY's roughly 7.8%; frequent wash sales across overlapping ETFs. | Practitioner | **Structural limitation**, estimate not rechecked. |
| 9 | After 2016 the six versions roughly tie SPY (11.7-16.8% against 14.4%); started fresh in 2016, 0 of 5 offsets beat SPY. The lead has decayed: mean annual excess 8.5% in 1999-2012, 1.8% in 2013-2024. | Quant, hostile reader | **Confirmed** (offset rows in `weekly_offsets_longhist.out`, `weekly.out`; decay figures are the reviewer's). |
| 10 | Wording: "US equity ETFs" (EFA and EEM are international, XLRE real estate); "16" (11 in 1999); "week-end offsets" (they are 5-session blocks); "simplified" (the paper's variant differs from the published CWMR). | Hostile reader | **Presentation defects**, confirmed. |
| 11 | The doc gives run 82's 2016-2024 return as 16.9% in one place and 16.8% in another. | Hostile reader | **Presentation defect** (day-count rounding); the database gives 16.83-16.87%. |
| 12 | Paired Sharpe test: correct Memmel-corrected Jobson-Korkie; returns show negative autocorrelation, so it is conservative. In-sample, the annual excess over SPY is +5.4% a year (t 3.22), positive in 19 of 26 years. | Quant | **No defect.** Recorded as evidence for the in-sample result, which does not answer findings 1-3. |
| 13 | Data: Yahoo closes match a fresh download; no missing sessions; dividends total-return without double counting; late joiners get the mean ratio and no weight until they trade; every fill is the last session of its ISO week; offset code phase-correct; benchmark reinvests dividends. | Auditor | **No defect.** |
| 14 | Lab runs store no git commit, so the database does not record which engine code made runs 80-83. | Auditor | **Minor provenance gap**, confirmed; reruns at 48be40f match. |

## Verdict

**Not ready to publish as "the strategy beats SPY", and not sound for real money as it stands.**
The arithmetic, data and code are correct and the headline numbers reproduce exactly. The lead
depends on four assumptions at once: filling at the close the signal was computed from, spreads
below about 7 bp in years when the tick size alone was 5-12 bp, no commissions, and a
tax-deferred account. With the fill one session later, the 1999-2015 lead over equal weight
nearly vanishes (7.3% against 6.6%) and 2016-2024 ties SPY. The one out-of-sample test of a
related variant on the holdout (monthly CWMR, 2025-2026) failed.

What the evidence supports, as a research note rather than a strategy claim: in a backtest that
fills at the signal's own close and charges 0.7 bp, weekly-bars CWMR on up to 16 US-listed ETFs
beat SPY in a pre-registered 1999-2015 window (11.5% against 4.9%; equal weight 6.6%) and over
1999-2024 (13.3% against 8.1%, not pre-registered). The lead falls to 9.8% with fills one
session later, disappears above about 7 bp per dollar traded, ignores commissions, and is
concentrated in 1-2 ETFs most weeks; after 2016 it roughly ties SPY.

Unverified: historical ETF spreads for 1999-2008 (no source found), the tax estimate, and the
reviewer's configuration count.
