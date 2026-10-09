# Adversarial review: revised working paper, October 8, 2026

## Under review

"Does Online Mean-Reversion Beat Equal Weight? A Reproduction and Pre-Registered Tests on
US-Listed ETFs", revised after the fill-timing fixes, with a new exploratory 1999-2024 section
(Table 7). Intended use: public working paper alongside the now-public btest repository.

## Snapshot

| Item | Identity |
|---|---|
| btest repository | commit `be9f47c` |
| docs/research/paper/cwmr-etf.tex | SHA-256 59b3512e9e5f84a9... |
| docs/research/paper/cwmr-etf.pdf | SHA-256 7bcf20deb2c6f514... |
| Replication repository | github.com/yelgabo/cwmr-etf-replication, commit `2226995` |

## Panel

Four independent reviewers, read-only, nothing run on data from 2025 on: a statistician
(inference, Table 7, the abstract's claim), a number auditor (every quantitative claim against
saved outputs and reruns), a code reviewer (trying to break the fill-timing fixes in both
repositories) and a hostile reader (consistency, the revision note, provenance claims). The
auditor and statistician reran `etf_tables.py` and `robustness.py`, which reproduced the saved
outputs byte for byte. Each finding below was checked against the code or outputs before its
disposition; agreement among reviewers is not proof.

## Findings and dispositions

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | Holm "smallest p is 0.11 / 0.15" holds only at 21-day blocks; at 126-day blocks weekly vs SPY over 1999-2015 is 0.029 after Holm. | Statistician | **Confirmed.** `robustness.py` now prints Holm at every block length; paper states the range. |
| 2 | Longer blocks give smaller p; the paper does not say why, and a data-driven block length or HAC test would be expected. | Statistician | **Partly confirmed.** Lag-1 autocorrelation of the return difference (-0.07) now printed and stated. Data-driven block length and a HAC column: **structural limitation**, not added. |
| 3 | Search over about 100 configurations not corrected. | Statistician, earlier reviews | **Missing evidence.** Discussion now compares z (1.5-2.0) with the expected maximum of 10 and 100 normals. Deflated Sharpe ratio still not computed. |
| 4 | Abstract and conclusion not scoped to 1999-2015 beside Table 7's p of about 0.05. | Statistician, hostile reader | **Confirmed.** Both now state the 1999-2024 result and its Holm-adjusted floor (0.19). |
| 5 | "Clearer" lead misreads a lower p from more, in-sample days; 65% overlap not stated. | Statistician, hostile reader | **Confirmed.** Reworded; overlap stated. |
| 6 | p = 0.049 printed to a precision 10,000 draws do not support. | Statistician | **Confirmed.** "About 0.05". |
| 7 | Bootstrap block starts exclude the last valid start (`n - block`), so the last day is never resampled. | Statistician | **Confirmed.** Fixed in both repositories (`n - block + 1`); all bootstrap p regenerated (third-decimal changes). Circular blocks and the `n // block` length: noted, not changed. |
| 8 | "Same Sharpe ratio" overstates p = 0.92. | Statistician | **Confirmed.** "Indistinguishable from". |
| 9 | Revision note buried in the deviations section and incomplete (Table 7, break-even change, sign flip vs EW, trade counts, renumbering). | Hostile reader, auditor | **Confirmed.** Moved to an unnumbered note after the abstract citing the first version's commits; lists every change. |
| 10 | "Reran both variants once" is stale: the revision is a third run on the pre-registered window. | Hostile reader | **Confirmed.** Stated. |
| 11 | Provenance overstated: plan 2 has a GitHub push record the paper omitted; plan 3 has only author-set times; replication READMEs still said "private". | Hostile reader | **Confirmed.** Paper states each plan's evidence; replication READMEs updated. |
| 12 | Section 4 "0.01 lower" is on raw returns while the quoted Sharpe ratios are over T-bills. | Hostile reader | **Confirmed.** Both given. |
| 13 | "Not measured before 2016" contradicts "no spreads at the open in any year". | Hostile reader | **Confirmed.** Reworded. |
| 14 | Roadmap calls Sections 4-6 out-of-sample; Section 6.2 is not. | Hostile reader | **Confirmed.** Reworded. |
| 15 | Replication labels "Section 6.4/6.3" stale after renumbering. | Hostile reader, auditor | **Confirmed.** Now 6.5 and 6.4. |
| 16 | Abstract's "measured spreads" does not cover 1999-2015 opening fills. | Hostile reader | **Confirmed.** Scoped to 15:45 in 2016-2024. |
| 17 | Equal weight 11.9% and 11.8% two sentences apart. | Hostile reader | **Confirmed presentation issue.** Sources (minute vs daily data) named. |
| 18 | "p = 0.51 with the original timing" not regenerated. | Hostile reader | **Rejected.** From `decompose.out:50`; `decompose.py` simulates its own close-to-close fills and does not use the engine. |
| 19 | Base of "0.4% of updates" unclear. | Hostile reader | **Confirmed.** "Of its 2,919 updates (learning from 1995)". |
| 20 | Revision note bounds: p moved up to 0.04, not 0.03; non-quoted returns moved more than 0.1. | Auditor | **Confirmed.** "At most 0.04"; "returns quoted here". |
| 21 | "3.5 percentage points per bp" is turnover times cost; measured is 4.0. | Auditor | **Confirmed.** "About 4". |
| 22 | "0.6 to 0.7 points" is 0.61-0.64; turnover "18x" is 17.5x; Section 2.4 omits Section 6.2 from the exploratory list. | Auditor | **Confirmed.** Fixed. |
| 23 | Trade counts 238-313 and correlation 0.98 had no saved output. | Auditor | **Confirmed.** `robustness.py` now prints both (238, 313, 290; 0.978). |
| 24 | btest sized a queued long-history order after overnight interest; the replication sized it at the decision. | Code reviewer | **Confirmed** (synthetic reproduction). btest now sizes at decision-day equity; no saved output changed (fully invested strategies). Test added. |
| 25 | Long history with splits, dividends or options would size a queued order on stale holdings. | Code reviewer | **Confirmed, latent** (no current caller). The engine now refuses them on long history. Test added. |
| 26 | Reverting fixes (b), (c) or (d) left the suite green. | Code reviewer | **Confirmed.** Tests added; each fails with its fix reverted. |
| 27 | Research log quotes stand-in results computed with same-close fills without saying so. | Code reviewer | **Confirmed.** Section labelled superseded and same-close. |
| 28 | Replication never decides on a calendar's last date; btest can. | Code reviewer | **No change.** Both callers pass calendars that run past the window. |

## Verdict

Ready for public use as a working paper. The confirmatory results are unchanged: both variants
pass the 1999-2015 pre-registered criterion, neither beats equal weight there, and the holdout
failure stands. The new Table 7 is exploratory and in-sample for 2016-2024; its lowest
unadjusted p against equal weight (about 0.05) is reported with its Holm-adjusted floor (0.19)
and the search caveat.

Remaining limits, unverified or not done: no data-driven block length or HAC test; no deflated
Sharpe ratio or reality check; the "about 100 configurations" count is approximate; the claim
that stored Yahoo closes match a fresh download to 3e-6 has no saved output.
