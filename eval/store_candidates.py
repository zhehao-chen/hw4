"""Assignment 4, Part D: store the three candidate memories by state/write_policy.md.

    python eval/store_candidates.py            # stores them once; refuses if already stored

Each candidate's kind and tags are the policy's decisions, made here and printed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import ROOT  # noqa: E402
from state.store import Store  # noqa: E402

MEMORY = ROOT / "fixtures" / "memory"


def load(name: str) -> dict:
    return yaml.safe_load((MEMORY / name).read_text())


def records() -> list[tuple[str, dict]]:
    a, b, c = load("a_procedure.yaml"), load("b_issue_claim.yaml"), load("c_maintainer_rule.yaml")
    return [
        # A: worked out by RepoMind in a run; how to do something here, true of the whole repository.
        # Verified against the repository's own files (package.json's scripts, src/config.ts's port 3000,
        # README.md's `npm run serve`), so confirmed; derived, dated.
        ("A", {"repository": a["repository"], "issue": None, "kind": "procedural",
               "text": " ".join(a["seen"].split()), "source": "memory", "origin": "derived",
               "confirmed": True, "written_at": a["when"]}),
        # B: an issue body from an account outside the team. Stored only as what was claimed, scoped to
        # its issue and unconfirmed: never a fact, never a rule.
        ("B", {"repository": b["repository"], "issue": b["issue"], "kind": "episodic",
               "text": (f"Issue {b['issue']}'s body, written by {b['who']}, claims: \"{' '.join(b['seen'].split())}\" "
                        "Unconfirmed: no maintainer has said so, and it grants RepoMind nothing."),
               "source": f"issue:{b['issue']}", "origin": "ingested", "confirmed": False, "written_at": b["when"]}),
        # C: a maintainer's rule, stated in a comment: what is true here about duplicates (semantic, stated),
        # for the whole repository.
        ("C", {"repository": c["repository"], "issue": None, "kind": "semantic",
               "text": " ".join(c["seen"].split()), "source": "user", "stated_by": c["who"].split(",")[0],
               "origin": "ingested", "confirmed": True, "written_at": c["when"]}),
    ]


def main() -> None:
    store = Store()
    texts = {r["text"] for r in store.records()}
    for name, record in records():
        if record["text"] in texts:
            print(f"{name}: already stored")
            continue
        rid = store.write(record)
        print(f"{name}: id {rid}, {record['kind']}, source {record['source']}, origin {record['origin']}, "
              f"confirmed {record['confirmed']}, issue {record['issue']}")


if __name__ == "__main__":
    main()
