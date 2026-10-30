"""Assignment 4, Part F: where a run's calls held the fact, read the way the checker reads them.

    python eval/forgetting.py "<the fact>" RUN_ID ...

For each run: every model call in trace order with its request number, purpose, how
many characters it was sent, whether the fact was in it and how far from the nearer
end; the compaction and store_read lines; and the comment the run posted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import ROOT  # noqa: E402
from harness.formats import parse_triage_comment, request_text, squeeze  # noqa: E402
from harness.tracker import Tracker  # noqa: E402


def jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def show(run_id: str, fact: str) -> None:
    trace = jsonl(ROOT / "runs" / f"{run_id}.jsonl")
    sent = {r["n"]: squeeze(request_text(r)) for r in jsonl(ROOT / "runs" / f"{run_id}.requests.jsonl")}
    issue = next((l.get("issue") for l in trace if l.get("type") == "run_start"), None)
    print(f"== {run_id}")
    for i, line in enumerate(trace):
        kind = line.get("type")
        if kind == "model_call":
            text = sent.get(line.get("request"), "")
            at = text.find(fact)
            depth = min(at, len(text) - (text.rfind(fact) + len(fact))) if at >= 0 else None
            calls = [c.get("name") for c in line.get("tool_calls") or []]
            print(f"  [{i:3}] call #{line.get('request')} {line.get('purpose') or '':8} {len(text):7,} chars  "
                  f"fact {'at ' + format(depth, ',') + ' from an end' if depth is not None else 'absent'}  {calls}")
        elif kind in ("compaction", "store_read", "note"):
            print(f"  [{i:3}] {kind}: " + json.dumps({k: v for k, v in line.items()
                                                      if k not in ("run_id", "t", "type", "text")}))
    comments = Tracker().comments(run_id=run_id, issue=issue)
    print("  comments:", [parse_triage_comment(c["body"]) for c in comments])


def main() -> None:
    fact = squeeze(sys.argv[1])
    for rid in sys.argv[2:]:
        show(rid, fact)


if __name__ == "__main__":
    main()
