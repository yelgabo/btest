# Adversarial review: working paper on CWMR and US-listed ETFs

## Under review

"Mean-Reversion Portfolio Selection on US-Listed ETFs, 1999-2026: A Replication with
Pre-Registered Tests", Yelnil Gabo, working paper dated October 7, 2026. Intended use:
submission to a journal or arXiv.

## Snapshot

| Item | Identity |
|---|---|
| btest repository | commit `da7c361`, clean tree |
| docs/research/paper/cwmr-etf.tex | SHA-256 df7272c2015bb9c9... |
| docs/research/paper/cwmr-etf.pdf | SHA-256 fa6f822d83f932f3... |
| docs/research/paper/refs.bib | SHA-256 b3f20ba612502c56... |
| Public replication repository | github.com/yelgabo/cwmr-etf-replication, commit `1b085ff` |

Private evidence behind the paper: the research log
`docs/research/2026-10-04-online-portfolio-selection-paper.md`, the earlier review
`docs/analysis/2026-10-06-weekly-cwmr-review.md`, scripts and outputs in
`docs/research/olps-replication/`, btest runs 84-89 and the holdout run 73 in the database.

## Panel

Four independent reviewers, read-only, nothing run on data from 2025 on: a journal referee
(methods and inference), a number auditor (about 120 quantitative claims against the replication
code, saved outputs, the database and public sources), a literature expert (citations, missing
work, fairness to the original paper) and a hostile reader and editor (contradictions, terms,
verifiability, AI disclosure, licensing). The replication code reproduced every cell of Tables
3, 5, 6 and 7 for three of them. The main findings were rechecked before synthesis; agreement
among reviewers is not proof.

Process note: the number auditor sent one request to sec.gov with the author's email address in
the User-Agent header, without the author's approval. The request was rate-limited and failed.

## Findings and dispositions

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | Abstract says the weekly lead over equal weight disappears between 5 and 10 bp. Against equal weight it disappears at about 4.5 bp (7.06% at 4 bp, 6.65% at 4.5 bp, 6.24% at 5 bp; equal weight 6.61%); 5-10 bp is the break-even against SPY. | Referee, auditor, hostile reader | **Confirmed error** (rechecked). |
| 2 | The pre-2001 tick-size argument ("sixteenths", "about 10 bp" on a $30 sector SPDR, "before April 2001") is unsupported. Amex, where the sector SPDRs listed, decimalised on 29 January 2001, not April. An SEC filing (SR-Amex-97-14) says SPDRs traded in 1/64ths, a 2.6 bp half-tick at $30, and no source was found for the Select Sector SPDRs' tick. | Auditor | **Confirmed unsupported**; the claim appears in the abstract, section 6.3 and the conclusion. |
| 3 | Jobson-Korkie with Memmel's correction assumes iid normal returns; the return differences have fat tails and volatility clustering. A 21-day block bootstrap gives weekly vs SPY p 0.026 (95% CI of the annual Sharpe difference +0.03 to +0.37), equal weight vs SPY p 0.024, monthly bars vs SPY p 0.073, weekly vs equal weight p 0.22 (CI -0.06 to +0.29). The conclusion against equal weight stands; the significance against SPY is understated. | Referee | **Confirmed** (rechecked with the replication code). Report bootstrap p-values and CIs beside JK. |
| 4 | Correlation range "0.71 to 0.95" omits equal weight vs SPY, 0.978. | Referee, auditor | **Confirmed error.** |
| 5 | "Untouched holdout ... used once": runs 10 (VolTarget) and 11 (SMA-200 trend filter) covered 2025-2026 on 3 October, two days before the CWMR pre-registration. | Auditor | **Confirmed** (database). Reword: no OLPS strategy had been run on it. |
| 6 | Introduction credits the Li and Hoi (2014) survey with "wealth multiples in the hundreds or thousands"; the survey has no results table. The algorithm papers report the multiples, and on some datasets they exceed 10^15. | Literature, auditor | **Confirmed citation error** (reviewer read the survey text; the 10^15 figure is the reviewer's, not rechecked). |
| 7 | Section 2.1 lists three differences from published CWMR; there are more (threshold on the log return, phi = inverse normal of theta, a diagonal covariance update, normalisation). | Literature | **Presentation defect**; details are the reviewer's reading of the AISTATS paper, not rechecked. Reword generally. |
| 8 | Missing related work: prior OLPS evaluations under transaction costs (Li et al. 2011 report CWMR break-even costs; Blum and Kalai 1999; the OLPS toolbox), the closest prior study (Moon, Kim and Moon 2019, mean reversion fails under costs), bid-ask bounce and liquidity provision, backtest-overfitting corrections. No contribution statement against this literature. | Literature | **Confirmed omission.** Each new citation must be checked before it is added. |
| 9 | "5-session blocks ending on each of the other four weekdays": there are five offsets and they count sessions, so they drift across weekdays at holidays. | Auditor, referee, hostile reader | **Confirmed error.** |
| 10 | Section 7: "holds only SPY until DIA launches ... and sits in cash before then" contradicts itself. With one symbol CWMR makes no decision, so it is in cash until its first trade in January 1998. | Auditor, hostile reader | **Confirmed error** (run 84: first trade 1998-01-30). |
| 11 | Discussion: weekly and monthly bars "beat SPY by roughly as much as an equal-weight portfolio does". Weekly beat SPY by 4.9 points, equal weight by 1.7. | Hostile reader | **Confirmed error.** |
| 12 | Conclusion: "costs these ETFs carried twenty years ago" is not supported (see 2). Spread-gap windows differ across abstract, 6.3 and 8 (2001-2010, 1999-2005, 1999-2010). | Hostile reader, auditor | **Confirmed.** |
| 13 | The 0.7 bp cost applied to 1999-2015 opening fills is not credible; spreads could be estimated from daily data (Corwin-Schultz, Abdi-Ranaldo). | Referee, hostile reader | **Structural limitation**; new analysis, author decision. |
| 14 | Delaying the weekly signal one more session cuts 1999-2015 from 9.82% to 7.36% (p vs equal weight 0.94): the cleanest test of the bid-ask-bounce explanation and not reported. | Referee | **Reviewer result, not rechecked**; worth adding. |
| 15 | Multiple testing acknowledged (about 100 configurations) but not corrected; the count is approximate and not documented. | Referee, hostile reader, auditor | **Confirmed limitation.** Give an exact count or call it approximate; consider a deflated Sharpe ratio. |
| 16 | Pre-registrations are private git commits; outsiders cannot verify timestamps. | Referee, hostile reader | **Structural limitation**, author decision: publish the registration texts with hashes in the replication repo, or retitle "pre-specified". |
| 17 | Deviations section omits selection history a reader would want: weekly bars were proposed after the holdout failed, and had failed a 2016-2024 offset check before its 1999-2015 pre-registration; the registered design said "fill at the close". | Referee | **Confirmed** (research log). |
| 18 | Characterisation of the original paper: acknowledge their stated walk-forward validation before calling the results in-sample; their stated sample is 1998-2010 but the data ends 2009-12-31; FTRL's problem is the data, not the algorithm. Cover (1991) gave one rule, not "some rules". | Literature | **Presentation defects**, confirmed against the research log. |
| 19 | AI disclosure: arXiv and Elsevier expect use of generative AI in the research process to be described, and the author to take responsibility. One sentence in the acknowledgments is thin. | Hostile reader | **Author decision**; suggested Methods sentence plus declaration. |
| 20 | Replication repo LICENSE should keep the original authors' MIT notice for the ported CWMR code; README should note that the Yahoo endpoint is unofficial. | Hostile reader | **Confirmed.** |
| 21 | Editorial: turnover 79x (Table 5) vs 76x (6.3) without windows; Table 7 blanks that the code fills (8.50%, -3.17%); "13 families three ways" vs "26 variants" (25: OLMAR not run on monthly bars); Table 6 Friday 16.4% vs section 6's 17.6% need a clause; "realistic trading" and "risk-adjusted returns" overstate; single author writing "we"; title says "Replication" but this is a reproduction plus new tests; captions need units; bibliography article numbers. | All | **Presentation defects.** |
| 22 | The autocorrelation figures in the Discussion have no saved script. | Referee, auditor | **Confirmed**; recomputed (-0.066/-0.091/-0.046/0.000 by the auditor, -0.065/-0.092/-0.047/0.000 by us). Add the script to the replication repo. |
| 23 | Holdout of 438 sessions: "tied" overstates what a test this short can show (CI on the Sharpe difference about +/-0.67). | Referee | **Presentation defect**; call it inconclusive. |
| 24 | Universe chosen with hindsight (today's liquid ETFs). | Referee | **Structural limitation**; state it. |

No numerical result in Tables 3 to 7 was found wrong: every cell reproduces from public code and
data, and the paper reports the corrected next-open runs throughout.

## Verdict

**Not ready to submit; a referee would ask for a major revision.** The numbers are right and the
negative conclusion follows from them, but the paper has five confirmed errors of statement
(findings 1, 2, 4, 9, 11, with 5, 6, 10 and 12), one inference gap that changes a reported
conclusion (finding 3: weekly bars is significant against SPY under a block bootstrap, though not
against equal weight), and a missing related-work section that a referee in this field would
treat as a reason to reject (finding 8). Findings 13 to 17 need the author's decisions or new
analysis.

Unverified: the reviewers' readings of the CWMR AISTATS paper and the survey (findings 6, 7),
the signal-delay result (14), the Select Sector SPDRs' actual tick size before 2001 (2).

## After correction

Applied in the paper and in the replication repository (commit `b91b30b`); every changed number
was rechecked by rerunning the public replication code:

- Fixed findings 1, 2, 4, 5, 6, 9, 10, 11, 12, 18, 21, 22, 23 and 24 as described above. The
  tick-size argument is removed; the abstract and section 6.3 give both break-evens (SPY 6-7 bp,
  equal weight about 4.5 bp: 7.06% at 4 bp, 6.65% at 4.5 bp against 6.61%).
- Finding 3: added Table 6 with block-bootstrap p-values and 95% intervals beside the
  Jobson-Korkie-Memmel test, and replaced the "conservative" sentence.
- Finding 7: the method section now says the authors' code describes its CWMR as a simplified
  version and lists the differences we verified, "among other differences".
- Finding 8: added a related-work paragraph and a contribution statement. All eleven new
  references were checked against Crossref, JMLR, PMLR or arXiv, and each claim made about them
  against its abstract or first page.
- Finding 14: added section 6.4; trading one session late gives 7.36% (Sharpe 0.35), bootstrap
  p against equal weight 0.92, reproduced in `etf_tables.py`.
- Finding 15: the configuration count is labelled approximate and the deflated Sharpe ratio named
  as the uncorrected next step.
- Finding 17: section 6 now states that the variants were proposed after the holdout result and
  that weekly bars failed the 2016-2024 offset check; section 7 states that the registered design
  filled at the close.
- Finding 20: the replication LICENSE keeps the original authors' MIT notice; the README notes
  that the Yahoo endpoint is unofficial and limited to personal use.

Still open (author decisions): finding 13 (estimated spreads before 2016), finding 16 (publish
the pre-registration texts or retitle as pre-specified), finding 19 (AI disclosure wording), and
the single author's "we".
