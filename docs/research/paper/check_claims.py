"""Checks the working paper against its claim ledger (claims.toml).

    uv run python docs/research/paper/check_claims.py

Every claim names where the paper states it and the saved evidence it rests on. When evidence
changes, the old strings stop matching and the claim is reported as stale, together with the
conclusion if it depends on that claim. A stale claim is re-derived from the current evidence,
which may reverse it; then the conclusion is re-derived from the claims; only then are the
paper and the ledger edited. Exit status 1 means something is stale.
"""
import os
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
BTEST = HERE.parents[2]
REPLICATION = Path(os.environ.get("CWMR_REPLICATION", BTEST.parent / "cwmr-etf-replication"))


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def source(path: str) -> str:
    repo, rel = path.split(":", 1)
    root = {"btest": BTEST, "replication": REPLICATION}[repo]
    return flat((root / rel).read_text())


ledger = tomllib.loads((HERE / "claims.toml").read_text())
paper = flat((HERE / "cwmr-etf.tex").read_text())
stale: dict[str, list[str]] = {}
for claim in ledger["claim"]:
    problems = [f"paper no longer says: {a!r}" for a in claim["paper"] if flat(a) not in paper]
    for path, text in claim["evidence"]:
        if flat(text) not in source(path):
            problems.append(f"evidence changed: {path} no longer contains {text!r}")
    if problems:
        stale[claim["id"]] = problems

conclusion = ledger["conclusion"]
conclusion_problems = [f"paper no longer says: {a!r}" for a in conclusion["paper"]
                       if flat(a) not in paper]
hit = [c for c in conclusion["depends_on"] if c in stale]
if hit:
    conclusion_problems.append(f"rests on stale claims {', '.join(hit)}")

# A number in the abstract, discussion or conclusion that no ledger anchor contains is a claim
# without recorded evidence.
anchors = " ".join(flat(a) for c in ledger["claim"] + [conclusion] for a in c["paper"])
summary_parts = re.findall(r"\\begin\{abstract\}(.*?)\\end\{abstract\}"
                           r"|\\section\{Discussion\}(.*?)\\section\*\{Data and code", paper)
unanchored = []
for part in (x for pair in summary_parts for x in pair if x):
    for sentence in re.split(r"(?<=[.;])\s+", part):
        nums = re.findall(r"\d+\.\d+", sentence)
        if nums and not any(n in anchors for n in nums):
            unanchored.append(sentence[:120])
for s in unanchored:
    print(f"UNRECORDED claim (no ledger anchor holds its numbers): {s}")

for cid, problems in stale.items():
    says = next(c["says"] for c in ledger["claim"] if c["id"] == cid)
    print(f"STALE {cid}: {says}")
    for p in problems:
        print(f"    {p}")
if conclusion_problems:
    print("STALE conclusion: re-derive it from the claims after fixing them")
    for p in conclusion_problems:
        print(f"    {p}")
if stale or conclusion_problems or unanchored:
    sys.exit(1)
print(f"{len(ledger['claim'])} claims and the conclusion match the paper and the evidence.")
