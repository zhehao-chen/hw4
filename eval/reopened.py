"""Assignment 4, Part D: the reopened issue, five runs with the store and five with an empty one.

    python eval/reopened.py --with-store ID ... --empty-store ID ...

Prints each run's store read, searches, file, pass, tool calls and tokens, and the
reopened block for reports/LAB_04.json. Passes by Assignment 1's check(), read from
the tracker by run_id.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.check_triage import check  # noqa: E402
from harness import ROOT  # noqa: E402
from harness.formats import parse_triage_comment  # noqa: E402
from harness.tracker import Tracker  # noqa: E402

ISSUE = 4207


def lines(run_id: str) -> list[dict]:
    return [json.loads(l) for l in (ROOT / "runs" / f"{run_id}.jsonl").read_text().splitlines() if l.strip()]


def answer() -> dict:
    data = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())
    return next(v[ISSUE] for v in data.values() if isinstance(v, dict) and ISSUE in v)


def summarize(run_ids: list[str], tracker: Tracker, key: dict) -> dict:
    rows = []
    for rid in run_ids:
        trace = lines(rid)
        calls = [l for l in trace if l.get("type") == "tool_call"]
        end = next(l for l in trace if l.get("type") == "run_end")
        read = next((l.get("records") for l in trace if l.get("type") == "store_read"), None)
        comments = tracker.comments(run_id=rid, issue=ISSUE)
        label, file = parse_triage_comment(comments[0]["body"]) if len(comments) == 1 else (None, None)
        searches = [c["input"].get("query") for c in calls if c.get("name") == "code_search"]
        rows.append({"run_id": rid, "store_read": read, "searches": searches, "label": label, "file": file,
                     "passed": check(tracker, rid, ISSUE, key), "tool_calls": len(calls),
                     "tokens": end["totals"]["total_tokens"]})
    for r in rows:
        print(f"  {r['run_id']}  read {r['store_read']}  {r['label']}, {r['file']}  "
              f"{'PASS' if r['passed'] else 'fail'}  {r['tool_calls']} calls  {r['tokens']} tok  searches {r['searches']}")
    n = len(rows)
    return {"runs": n, "passes": sum(r["passed"] for r in rows),
            "mean_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 2),
            "mean_tokens": round(sum(r["tokens"] for r in rows) / n), "run_ids": run_ids}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--with-store", nargs=5, required=True)
    p.add_argument("--empty-store", nargs=5, required=True)
    a = p.parse_args()
    tracker, key = Tracker(), answer()
    out = {}
    for name, ids in (("with_store", a.with_store), ("empty_store", a.empty_store)):
        print(name)
        out[name] = summarize(ids, tracker, key)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
