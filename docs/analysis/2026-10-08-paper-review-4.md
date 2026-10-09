# Adversarial review: working paper with all ETF results over 1999-2024

## Under review

"Does Online Mean-Reversion Beat Equal Weight?", rewritten to report every ETF result over one
window, 1999-2024, on daily data (decide on the close, fill at the next open). Intended use:
public working paper alongside the public btest and replication repositories.

## Snapshot

| Item | Identity |
|---|---|
| btest repository | commit `2ea7bca` |
| docs/research/paper/cwmr-etf.tex | SHA-256 7cab25256458926e... |
| docs/research/paper/cwmr-etf.pdf | SHA-256 e37dcc040290c388... |
| Replication repository | github.com/yelgabo/cwmr-etf-replication, commit `be6ff1e` |

## Panel

Four independent reviewers, read-only, nothing run on data from 2025 on: a statistician, a number
and code auditor, a practitioner (execution and costs at the open) and a hostile reader. The
auditor reran `etf_tables.py`, `robustness.py` and `autocorrelation.py`; all matched the saved
outputs byte for byte. Every finding below was checked against code or data before its
disposition; agreement among reviewers is not proof.

The author decided two points before the review: all ETF results use one window, and the paper
carries no version history. Where a finding conflicted with the first, the author chose how to
resolve it.

## Findings and dispositions

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | Daily CWMR's lead over EW comes almost entirely from 1999-2008 (10.3% vs 1.7%), when 0.7 bp at the open is not credible; over 2009-2024 it trails SPY. Weekly bars' lead is mostly 2009-2024, which includes its selection years. | Practitioner | **Confirmed** (recomputed). **Author decision:** one sentence each in the costs section and abstract, no sub-period tables. Source added to `robustness.py`. |
| 2 | Bounce in opening prices is not ruled out; "bounce in closing prices does not explain its gain" leaves it out. | Practitioner, hostile reader | **Confirmed.** Discussion now lists it as the first of three explanations; "which a trader can capture" removed. The by-period regression the practitioner proposed was not added (single-window decision). |
| 3 | "Fills that could have been executed" overstates; Yahoo opens are single prints, not auction prices. | Practitioner | **Confirmed.** Reworded; Section 2.2 says what the open is and that it cannot be checked against an auction in the early years. |
| 4 | Commission drag of the daily schedule omitted; fractional shares assumed. | Practitioner | **Confirmed** (1,000-1,190 trades a year in 1999-2001). Added. |
| 5 | The 0.7 bp caveat is buried. | Practitioner | **Confirmed.** In the abstract. |
| 6 | Disorderly opens (2015-08-24), halts not mentioned. | Practitioner | **Confirmed** (XLK low 15% below its open that day). One sentence added. |
| 7 | SEC fee rate varied; taxes and wash sales. | Practitioner | **Presentation.** "Although the rate varied" and wash-sale rules added; the historical rates were not checked. |
| 8 | The headline return lead and break-evens are never tested; only Sharpe ratios are. | Statistician | **Confirmed.** Return-lead bootstrap added (`robustness.py`): daily and weekly vs EW +3.4 points, p 0.021; after Holm over nine, smallest 0.085, vs EW 0.15. Abstract and conclusion reworded. Break-even intervals not added. |
| 9 | Weekly bars' selection history omitted. | Statistician, hostile reader | **Confirmed** (git history). Section 2.4 now gives the order of the work. |
| 10 | "About 4 percentage points" overstates (3.7; weekly 2.6 over offsets). | Statistician | **Confirmed.** Fixed. |
| 11 | 170x turnover understates the trading that drives cost drag (230x a year on average, 358-410x in 1999-2005). | Statistician | **Confirmed.** Per-year turnover added to `robustness.py` and the costs section. |
| 12 | The z-versus-expected-maximum argument should use two-sided |z| (about 2.7) and note correlated configurations. | Statistician, auditor | **Confirmed.** Fixed; reference now to Section 4, not Table 5. |
| 13 | Block-length explanation incomplete; daily vs SPY is not monotone. | Statistician | **Confirmed.** Variance ratios cited; "mostly". |
| 14 | Table 5 difference is a raw-return Sharpe difference. | Statistician | **Confirmed.** Caption says so. |
| 15 | The open-to-open coefficient has no standard error. | Statistician | **Confirmed.** Clustered by week: -3.3 (s.e. 1.2), +0.1 (s.e. 0.6). |
| 16 | Title promises pre-registered tests of the question it asks. | Hostile reader | **Author decision:** "A Reproduction and Tests of CWMR on US-Listed ETFs". |
| 17 | 6.80% vs 9.33% compares a strategy in cash until 1998 with SPY. | Hostile reader | **Confirmed.** From its first fill: 7.05% vs SPY 6.03% (`paper_sections_4_5.out`). Both stated. |
| 18 | "Before the tests above" hides the order of the work. | Hostile reader | **Confirmed.** See 9. |
| 19 | Update count 2,919 double-counts copy updates. | Hostile reader, auditor | **Confirmed.** 6 of 1,563. |
| 20 | "Holdout used once" contradicts Section 2.4. | Hostile reader | **Confirmed.** Fixed. |
| 21 | "No better than equal weight" contradicts 0.49 vs 0.42. | Hostile reader | **Confirmed.** "Not significantly better (p = 0.40)". |
| 22 | "After correcting for the comparisons made" overstates Holm's scope. | Hostile reader | **Confirmed.** "The nine comparisons we report"; Section 2.4 says Holm does not cover the search. |
| 23 | "Every table except the holdout is independently replicated" excludes the spread table and overstates independence (same algorithm code). | Hostile reader, auditor | **Confirmed.** Reworded. |
| 24 | Holm values promised but only two printed. | Hostile reader | **Confirmed.** Holm column added to Table 5. |
| 25 | Stale section labels in the replication repository and its pre-registration notes; rerun count disagrees. | Hostile reader, auditor | **Confirmed.** Fixed. |
| 26 | "Tables 3 and 4 of Lahanis" next to this paper's Table 3. | Hostile reader | **Confirmed.** "Their Tables 3 and 4". |
| 27 | "Learns from 1995" is mostly empty before DIA in 1998. | Hostile reader | **Confirmed.** Explained in Section 2.2. |
| 28 | "Two procedures" lists three items. | Auditor | **Confirmed.** Reworded. |
| 29 | Holdout figures had no saved output. | Auditor | **Confirmed.** `holdout_run73.py` reads stored run 73 (no rerun): 438 daily returns, 8 of 21 full months. |
| 30 | Script docstrings with wrong table or section numbers; equal-weight docstring; EFA "a few sessions". | Auditor | **Confirmed.** Fixed. |

## Verdict

Ready for public use as a working paper. Its conclusion, no statistically significant edge over
equal weight after correcting for the comparisons reported, survives every check, including the
new return-lead test (smallest Holm-adjusted p 0.085). The paper now states the facts that most
weaken the positive numbers: where each lead comes from, the order of the work, and the costs at
the open that were never measured. All 1999-2024 results are exploratory; the out-of-sample
evidence is the failed holdout and the registered 1999-2015 test against SPY.

Remaining limits: spreads at the open never measured; no deflated Sharpe ratio or reality check
over the roughly 100 configurations (the count itself is approximate); break-even intervals not
reported; historical SEC fee rates and the 1999 commission figure not rechecked against their
sources in this review.
