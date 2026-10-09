# Adversarial review: claim ledger and the paper's stale claims

## Under review

The claim ledger (`docs/research/paper/claims.toml`), its checker (`check_claims.py`) and the
pre-commit hooks, as a way to keep the working paper's claims and conclusion consistent with its
evidence after any change; and the paper itself for stale or unsupported claims.

## Snapshot

| Item | Identity |
|---|---|
| btest repository | commit `482a607` |
| cwmr-etf.tex | SHA-256 998b2fe0b3fdacb4... |
| claims.toml | SHA-256 535ac5762de8a466... |
| check_claims.py | SHA-256 b01463de28fa757a... |
| Replication repository | commit `5f96f67` |

## Panel

Three independent reviewers, read-only, nothing run on 2025 onward: a mechanism breaker (tried
to make the paper stale without the checker or hooks noticing, on scratch copies), an independent
claim auditor (listed the paper's claims before opening the ledger, then compared), and a
hostile reader. Findings were checked against code, outputs and git before disposition.

## Findings and dispositions

| # | Finding | Raised by | Disposition |
|---|---|---|---|
| 1 | Claims about sets ("every", "smallest", "none") quoted only some rows; changing an unquoted row passed. | Breaker | **Confirmed** (5 reproductions). Evidence now matches whole lines; set claims list every row. All 5 now caught. |
| 2 | Prose could reverse ("neither ... significant" to "both ... significant") or gain a clause while a fragment anchor survived. | Breaker | **Confirmed.** Every sentence, caption, table row and heading must appear whole in one claim or in `no_claim`. Both now caught. |
| 3 | Coverage regex: `any` not `all`, substring matches, integers ignored, renamed section bypassed it, body tables unchecked. | Breaker | **Confirmed.** Replaced by whole-unit coverage of the entire paper, tables included. All reproductions now caught. |
| 4 | Conclusion's dependencies incomplete; unknown ids, duplicates, empty evidence accepted. | Breaker, auditor | **Confirmed.** The conclusion now depends on every claim except three exempted with reasons; unknown ids, duplicates, empty evidence and doubly claimed units are errors. |
| 5 | Comparison claims held one side; derived arithmetic had no source. | Breaker, auditor | **Confirmed.** Both operands cited; commission, tick, lead, |z| and chance figures, the XLK move, the universe size and the search size are now printed by `robustness.py`, `spreads.py` and `search_size.py`. |
| 6 | Hooks checked the working tree, skipped generator-code changes, were unversioned, absent from fresh clones, bypassed by `--no-verify`; no replication pin. | Breaker | **Confirmed.** Hooks in tracked `.githooks/` check an export of the index (a staged stale holdout file is now refused), refuse generator changes without regenerated outputs, and the replication commit is pinned. CI (`.github/workflows/claims.yml`) runs the check on every push against the pinned replication commit. `--no-verify` still skips the local hook; CI then fails. |
| 7 | Replication hook's message when `../btest` is missing. | Breaker | **Confirmed.** Now says `../btest` was not found. |
| 8 | "Only then did we try weekly and monthly bars": monthly bars were in the first search (`dcc42b0`, 14 minutes before the holdout plan). | Auditor | **Confirmed, false claim.** Fixed; git evidence in C18. |
| 9 | "The holdout plan's pipeline check": the check was in the 1995-2015 plan. | Auditor | **Confirmed, false claim.** Fixed; evidence in C35. |
| 10 | "Every result except the spread table and the holdout" is replicated: the 2016-2024 search and the 1995-2015 test are btest only; Section 3 partly btest only. | Auditor | **Confirmed.** Both statements reworded. |
| 11 | "When costs were higher" / "not available" stronger than the evidence. | Auditor, hostile reader | **Confirmed.** "Probably", with the tick arithmetic stated. |
| 12 | "About 100 configurations" uncounted. | Auditor | **Confirmed.** Counted from saved outputs: 115 (`search_size.out`). |
| 13 | "Mean-reversion algorithms multiply wealth hundreds to over a thousand times" holds only for the best two. | Auditor | **Confirmed.** "The best". |
| 14 | 1,563 updates include 1995-1998; autocorrelation "over several weeks" shown only for weekly bars. | Auditor | **Confirmed.** Both reworded. |
| 15 | Replication README title stale. | Auditor | **Confirmed.** Fixed. |
| 16 | Conclusion "no evidence" stronger than the abstract and the 0.006 unadjusted p. | Hostile reader | **Confirmed.** "Do not establish" in both. |
| 17 | Discussion's "the original results are real" contradicts Section 3. | Hostile reader | **Confirmed.** Rewritten. |
| 18 | Title question never answered directly. | Hostile reader | **Confirmed.** The conclusion opens with the answer. |
| 19 | The equal-weight-isolates line repeated three times; Section 4 argued two ways. | Hostile reader | **Confirmed.** Abstract clause removed; Section 4 states the two leads are of similar size and only the SPY one clears the threshold. |
| 20 | 3.7 and 3.4 point leads unexplained; block lengths never listed; "tells a stronger story"; "that plan"; deviations count; Section 3 "keeps much of its return". | Hostile reader | **Confirmed.** All fixed. |

## Verdict

The mechanism now catches every bypass the breaker demonstrated, rerun against it on scratch
copies (row changes in sets, prose reversals, appended clauses, renamed sections, swapped numbers
and integers, table cells, regression sign flips, holdout reversal, removed git evidence, unknown
exemptions, empty evidence, a stale staged file, a generator change without outputs). CI passes on
a fresh clone at the pinned replication commit.

What it cannot do: judge whether a claim's wording follows from its evidence. It forces every
sentence to be tied to evidence and flags every change, but re-deriving a flagged claim, and
deciding that the cited evidence supports it, remain judgement; the two false claims in this
review were sentences no checker could have caught before every sentence had to be recorded. 12
evidence items rest on outside sources (citations, the 1999 SEC report, decimalisation, ETF
launch dates, the SEC fee rate) and are not checked. Local hooks need `git config core.hooksPath
.githooks` in each clone; CI does not.
