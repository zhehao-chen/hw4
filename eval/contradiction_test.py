"""Assignment 4, Part E, task 2: the contradiction test, three sessions on the real store.

    python eval/contradiction_test.py 1    # session 1: the maintainer's rule on duplicates is stored (candidate C)
    python eval/contradiction_test.py 2    # session 2: the maintainer changes the rule; it supersedes the old one
    python eval/contradiction_test.py 3    # session 3: retrieve the rule on duplicates; prints the IDs

Each session is its own process, so nothing passes between them but the store.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.store_candidates import records as candidates  # noqa: E402
from state.store import REPOSITORY, Store  # noqa: E402

TOPIC = r"duplicate"
# Session 2's statement: the same maintainer, later, reversing the part about closing.
NEW_RULE = {"repository": REPOSITORY, "issue": None, "kind": "semantic", "source": "user", "stated_by": "priya-s",
            "origin": "ingested", "confirmed": True, "written_at": "2026-10-28T10:30:00Z",
            "text": ("For duplicates: label them `duplicate`, link the original, and close them yourself once the "
                     "link is posted. I no longer close duplicates by hand.")}


def rules(store: Store) -> list[dict]:
    """The maintainers' active rules on duplicates."""
    return [r for r in store.search(REPOSITORY, TOPIC) if r["source"] == "user"]


def session(n: int) -> None:
    store = Store()
    if n == 1:
        c = dict(candidates())["C"]
        found = [r for r in store.records() if r["text"] == c["text"]]
        rid = found[0]["id"] if found else store.write(c)
        print(f"session 1: the rule on duplicates is record {rid}")
    elif n == 2:
        if any(r["text"] == NEW_RULE["text"] for r in store.records()):
            print("session 2: already stated")
            return
        old = rules(store)
        if len(old) != 1:
            raise SystemExit(f"session 2: want one active rule on duplicates to supersede, found {len(old)}")
        rid = store.supersede(old[0]["id"], NEW_RULE)
        print(f"session 2: record {rid} supersedes record {old[0]['id']}, which stays, inactive")
    else:
        found = rules(store)
        print(f"session 3 retrieved: {[r['id'] for r in found]}")
        for r in found:
            print(f"  [{r['id']}] supersedes {r['supersedes']}, stated by {r.get('stated_by')}, "
                  f"{r['written_at']}: {r['text']}")
        print("  every record on the subject:", [(r["id"], "active" if r["active"] else "inactive")
                                                 for r in store.records() if r["source"] == "user"])


if __name__ == "__main__":
    session(int(sys.argv[1]))
