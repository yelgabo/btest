"""Checks the working paper against its claim ledger (claims.toml).

    uv run python docs/research/paper/check_claims.py          # check
    uv run python docs/research/paper/check_claims.py --list   # print the paper's units

The paper is split into units: sentences of prose and rows of tables. Every unit must appear,
word for word, in exactly one claim's `paper` list or in `no_claim`; so a new or edited sentence
fails until the ledger records it. Every claim lists evidence that must still hold:

    ["output", "replication:expected/etf_tables.txt", "<one or more whole lines>"]
    ["git", "btest", "<hash>", "<text in that commit's date and subject>"]
    ["external", "<source the reader can check; not checked here>"]

Output evidence matches whole lines (whitespace collapsed), so a claim about a set of rows must
list every row. When evidence or a unit changes, the claim is stale; so is the conclusion unless
the claim is exempted with a reason. A stale claim is re-derived from the current evidence, which
may reverse it; then the conclusion; then the paper and the ledger are edited together.

The replication repository must be checked out clean at the commit the ledger pins.
"""
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(os.environ.get("CLAIMS_DIR") or Path(__file__).resolve().parent)
BTEST = Path(os.environ.get("CLAIMS_BTEST") or Path(__file__).resolve().parents[3])
REPLICATION = Path(os.environ.get("CWMR_REPLICATION", BTEST.parent / "cwmr-etf-replication"))
REPOS = {"btest": BTEST, "replication": REPLICATION}


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def units(tex: str) -> list[str]:
    """Sentences of prose and rows of tables, from the abstract to the bibliography."""
    body = tex[tex.index(r"\begin{abstract}"):tex.index(r"\bibliographystyle")]
    body = re.sub(r"(?<!\\)%.*", "", body)
    out: list[str] = []
    for m in re.finditer(r"\\begin\{tabular\}\{[^}]*\}(.*?)\\end\{tabular\}", body, re.S):
        for row in m.group(1).split(r"\\"):
            row = flat(re.sub(r"\\(top|mid|bottom)rule", " ", row))
            if row:
                out.append("ROW: " + row)
    body = re.sub(r"\\begin\{tabular\}.*?\\end\{tabular\}", " ", body, flags=re.S)
    body = re.sub(r"\\caption\{(.*?)\}\\label\{[^}]*\}",
                  lambda m: "\n\nCAPTION: " + flat(m.group(1)) + "\n\n", body, flags=re.S)
    body = re.sub(r"\\(?:sub)*section\*?\{([^}]*)\}(?:\\label\{[^}]*\})?|\\paragraph\{([^}]*)\}",
                  lambda m: "\n\nHEADING: " + (m.group(1) or m.group(2)) + "\n\n", body)
    body = re.sub(r"\\begin\{align\}.*?\\end\{align\}", " [equations] ", body, flags=re.S)
    body = re.sub(r"\\(begin|end)\{[a-z]+\}(\[[^]]*\])?", " ", body)
    body = re.sub(r"\\(centering|item)\b", " ", body)
    for block in re.split(r"\n\s*\n", body):
        block = flat(block)
        if not block:
            continue
        if block.startswith(("CAPTION: ", "HEADING: ")):
            out.append(block)
            continue
        out += [flat(s) for s in re.split(r"(?<=[.?])\s+(?=[A-Z\\$(])", block) if flat(s)]
    return out


def git_line(repo: str, commit: str) -> str:
    # A hook checks an exported copy of the index, which has no history; it names the repository.
    where = os.environ.get(f"CLAIMS_GIT_{repo.upper()}") or REPOS[repo]
    return subprocess.run(["git", "-C", str(where), "log", "-1", "--format=%h %cI %s", commit],
                          capture_output=True, text=True).stdout.strip()


def output_lines(path: str) -> list[str]:
    repo, rel = path.split(":", 1)
    return [flat(x) for x in (REPOS[repo] / rel).read_text().splitlines() if flat(x)]


def holds(ev: list[str]) -> str | None:
    """None if the evidence holds, else why not."""
    kind = ev[0]
    if kind == "output":
        try:
            lines = output_lines(ev[1])
        except OSError as e:
            return f"{ev[1]} cannot be read ({e.strerror})"
        want = [flat(x) for x in ev[2].splitlines() if flat(x)]
        for i in range(len(lines) - len(want) + 1):
            if lines[i:i + len(want)] == want:
                return None
        return f"{ev[1]} no longer has the line(s) {ev[2]!r}"
    if kind == "git":
        line = git_line(ev[1], ev[2])
        return None if line and flat(ev[3]) in line else f"git {ev[1]} {ev[2]}: {line!r}"
    if kind == "external":
        return None
    return f"unknown evidence kind {kind!r}"


def main() -> int:
    ledger = tomllib.loads((HERE / "claims.toml").read_text())
    paper_units = units((HERE / "cwmr-etf.tex").read_text())
    if "--list" in sys.argv:
        for u in paper_units:
            print(u)
        return 0
    errors: list[str] = []

    # The replication repository's own pre-commit hook checks staged evidence before that commit
    # exists, so it skips the pin; every other check enforces it.
    skip_pin = os.environ.get("CLAIMS_SKIP_PIN") == "1"
    pinned = ledger["replication_commit"]
    head = subprocess.run(["git", "-C", str(REPLICATION), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(REPLICATION), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if not skip_pin and not head.startswith(pinned):
        errors.append(f"replication is at {head[:7] or 'nothing'}, the ledger pins {pinned}")
    if not skip_pin and dirty:
        errors.append("replication has uncommitted changes:\n      " + dirty.replace("\n", "\n      "))

    claims = ledger["claim"]
    ids = [c["id"] for c in claims]
    for cid in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"duplicate claim id {cid}")
    exempt = ledger["conclusion"].get("exempt", {})
    for cid in exempt:
        if cid not in ids:
            errors.append(f"conclusion exempts unknown claim {cid}")

    owner: dict[str, str] = {}
    for c in claims:
        if not c.get("evidence"):
            errors.append(f"{c['id']} has no evidence")
        for u in c["paper"]:
            if flat(u) in owner:
                errors.append(f"unit claimed twice ({owner[flat(u)]}, {c['id']}): {u[:80]}")
            owner[flat(u)] = c["id"]
    for u in ledger.get("no_claim", []):
        owner.setdefault(flat(u), "no_claim")

    stale: dict[str, list[str]] = {}
    for c in claims:
        why = [f"paper no longer has: {u[:100]!r}" for u in c["paper"]
               if flat(u) not in paper_units]
        why += [w for ev in c.get("evidence", []) if (w := holds(ev))]
        if why:
            stale[c["id"]] = why
    unrecorded = [u for u in paper_units if u not in owner]
    gone_no_claim = [u for u in ledger.get("no_claim", []) if flat(u) not in paper_units]

    for cid, why in stale.items():
        says = next(c["says"] for c in claims if c["id"] == cid)
        print(f"STALE {cid}: {says}")
        for w in why:
            print(f"    {w}")
    hit = [cid for cid in stale if cid not in exempt]
    if hit:
        print(f"STALE conclusion: rests on {', '.join(hit)}; re-derive it after those claims")
    for u in unrecorded:
        print(f"UNRECORDED unit (add it to a claim or to no_claim): {u}")
    for u in gone_no_claim:
        print(f"no_claim unit no longer in the paper: {u[:100]}")
    for e in errors:
        print(f"ERROR {e}")
    external = sum(1 for c in claims for ev in c.get("evidence", []) if ev[0] == "external")
    if stale or unrecorded or gone_no_claim or errors:
        return 1
    print(f"{len(claims)} claims cover all {len(paper_units)} units; evidence holds; "
          f"{external} items rest on outside sources not checked here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
