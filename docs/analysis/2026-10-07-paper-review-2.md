# Second adversarial review: working paper on CWMR and US-listed ETFs

## Under review

"Does Online Mean-Reversion Survive Trading Costs? A Reproduction and Pre-Registered Tests on
US-Listed ETFs", Yelnil Gabo, working paper dated October 7, 2026, after the corrections from the
first review (`docs/analysis/2026-10-07-paper-review.md`). Intended use: submission to a journal
or arXiv.

## Snapshot

| Item | Identity |
|---|---|
| btest repository | commit `c9380c4` |
| docs/research/paper/cwmr-etf.tex | SHA-256 5eb3decb3bd40286... |
| docs/research/paper/cwmr-etf.pdf | SHA-256 f12e76c75a97dfb8... |
| docs/research/paper/refs.bib | SHA-256 7ce753df3ea6da42... |
| Public replication repository | github.com/yelgabo/cwmr-etf-replication, commit `4a510f4` |

## Panel

Four fresh reviewers, read-only, nothing run on data from 2025 on, and each told not to send
the author's email or name to any outside site: a referee (methods and inference), a number
auditor (75 claims), a literature expert (every citation and DOI) and a hostile reader and
editor. All replication outputs matched `expected/`; the three published plan texts matched
their commits. Main findings were rechecked with `robustness.py` before synthesis.

## Findings and dispositions

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | The holdout failed its pre-registered rule (CAGR and Sharpe both below SPY) but the paper said "matched" and "inconclusive". | Referee, hostile reader | **Confirmed.** Abstract, Section 5 and conclusion now say it failed. |
| 2 | The Discussion credited the one-session-late drop to bid-ask bounce in closing prints, but fills are at the open. | Referee | **Confirmed and rechecked**: per 1% weekly excess move, close to next open -1.4 bp and next open to the open after -3.3 bp (1999-2015); +2.9 and -3.4 bp (2016-2024). Section 6.4 and the Discussion now say the reversal is in a tradable leg and persists after 2016, so the open-time spread decides it. |
| 3 | Bootstrap significance against SPY depends on block length; the bootstrap is not studentised. | Referee | **Confirmed**: weekly vs SPY p 0.111 (1-day) to 0.006 (126-day); vs EW 0.139-0.328; monthly vs EW 0.343-0.508. Reported in 6.1 with the sensitivity, the non-studentised caveat and Ledoit and Wolf's studentised alternative. A studentised bootstrap was not implemented. |
| 4 | Multiple testing not applied. | Referee | **Fixed**: Holm-adjusted smallest p 0.111, reported. Deflated Sharpe ratio still not computed (stated). |
| 5 | Post-plan analyses on the confirmatory window not labelled exploratory. | Referee | **Fixed** in Section 2.4. |
| 6 | Section 7's drop from 11.57% to 6.79% mixes two changes. | Referee | **Fixed**: 7.32% with same fills, 6.79% with corrected fills. |
| 7 | 11.2% continuous figure had no source. | Referee | **Rejected**: the auditor matched it to run 85 (11.17% vs 14.38%). |
| 8 | "Fires every period" is wrong. | Auditor | **Confirmed**: 12 of 2,919 updates (0.41%) do not fire. Fixed. |
| 9 | "26 seconds" mixes sources. | Auditor, hostile reader | **Fixed**: GitHub push 10:06:06 UTC, database run 10:06:32 UTC, each named. |
| 10 | The 1999-2015 window had also been seen by equal weight. | Auditor | **Fixed.** |
| 11 | Funds join on their first day in the Yahoo data, a few sessions after launch for IWM, EFA, EEM; the two-fund minimum contradicted the weight-splitting rule. | Auditor, hostile reader | **Fixed** in 2.2. |
| 12 | SEC fee is the 2026 rate applied to all years; commission needs a source. | Auditor | **Fixed**; SEC report (Unger, 1999) verified and cited. |
| 13 | Concentration figures came from a deleted run. | Auditor | **Rechecked** on current code: median 2, 36%. Now printed by `robustness.py`. |
| 14 | Discussion switched benchmark; 5 of 6 weekly versions still beat EW after 2016; summary omitted monthly losses. | Hostile reader | **Confirmed and fixed.** |
| 15 | Roll (1984) does not measure the share of reversal due to bounce; Ledoit and Wolf propose a test; missing DeMiguel et al. (1/N) and OLMAR citation; "sector and index ETFs"; "publicly released". | Literature | **Fixed**; Kaul and Nimalendran (1990), Conrad, Gultekin and Kaul (1997, issue 3, not 4 as reported), DeMiguel et al. (2009), Li et al. (2015) verified in Crossref and added. |
| 16 | Contribution sentence misparsed; "their Tables 3 and 4" ambiguous; sample years at first mention; abbreviations undefined; "close-to-close timing" undefined. | Literature, hostile reader | **Fixed.** |
| 17 | Abstract too long and led with the uninformative SPY comparison. | Hostile reader | **Fixed**, about 170 words, leads with the equal-weight result. |
| 18 | Replication tables labelled differently from the paper; plan 3 "before 1999" vs paper "before 2016". | Auditor, hostile reader | **Fixed** in the replication repo (`7cd9fdc`). |
| 19 | Title asks about costs while the main result is about the benchmark. | Hostile reader | **Author decision.** |
| 20 | Public commits show a personal email address. | Hostile reader | **Author decision.** |
| 21 | Sections 4-5 not publicly reproducible; Kunsch (1989) has no pages; 45-session spread sample is small. | Referee, literature | **Structural limitations**, stated or left. |

## Verdict

**Close to submittable; the referee recommended minor revision before these fixes.** No
reported number was wrong. The fixes change how three results are described: the holdout is a
failure, the weekly reversal is real and tradable at the open rather than an artefact of
closing prices, and significance against SPY depends on the bootstrap's block length while the
conclusion against equal weight does not. Remaining: the title (finding 19), the public email
(20), and the unimplemented studentised bootstrap and deflated Sharpe ratio, both stated in
the paper as not done.
