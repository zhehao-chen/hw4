"""Assignment 4, Parts B and C: run the crash matrix and count it from the tracker.

For every step N from 1 to --steps, and each of after and during, it runs

    python run.py --way planned --issues 4201 --die-<when>-step N
    python run.py --resume <run_id>

and then reads the tracker by that run_id: the comments on the issue, the open PRs
from repomind/issue-<n>, and whether the result matches the run's own last
checkpointed findings. KEY_MODE is passed through from the environment to the
crashed run (the resume keeps the run's own switches). It prints one JSON entry per
case, in LAB_04.json's shape, to stdout and to --out.

    python eval/crash_matrix.py --steps 5 --out runs/matrix_derived.json
    KEY_MODE=uuid python eval/crash_matrix.py --steps 5 --out runs/matrix_uuid.json
    python eval/crash_matrix.py --steps 5 --backend harness.scripted:ScriptedTriage   # free

A kill whose step the run never reached does not fire; the case is run again, up to
--tries times. Only `count` mode (--count run_id ...) reads existing runs without
running anything.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.formats import normalize_path, parse_triage_comment  # noqa: E402
from harness.trace import read_trace  # noqa: E402
from harness.tracker import Tracker  # noqa: E402
from state.checkpointer import Checkpointer  # noqa: E402

KILLED = re.compile(r"killed (\S+) ")


def count(run_id: str, issue: int) -> dict:
    tracker = Tracker(ROOT)
    comments = tracker.comments(run_id, issue)
    prs = tracker.prs(run_id, branch=f"repomind/issue-{issue}")
    last = Checkpointer().last(run_id) or {}
    findings = last.get("findings") or {}
    matches = False
    if len(comments) == 1 and findings.get("label") and findings.get("file"):
        label, file = parse_triage_comment(comments[0]["body"])
        want = normalize_path(str(findings["file"]))
        matches = (label, file) == (str(findings["label"]).lower(), want) and len(prs) == (0 if want == "none" else 1)
    start = read_trace(ROOT / "runs" / f"{run_id}.jsonl")[0]
    die = start.get("die") or {}
    return {"run_id": run_id, "step": die.get("step"), "when": die.get("when"), "comments": len(comments),
            "open_prs": len(prs), "matches": matches, "comment_ids": [c["id"] for c in comments],
            "findings": {"label": findings.get("label"), "file": findings.get("file")}}


def one_case(when: str, step: int, issue: int, backend: str | None, tries: int) -> dict | None:
    for attempt in range(1, tries + 1):
        cmd = [sys.executable, "run.py", "--way", "planned", "--issues", str(issue), f"--die-{when}-step", str(step)]
        if backend:
            cmd += ["--backend", backend]
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        found = KILLED.search(out.stderr + out.stdout)
        if not found:
            print(f"  {when} {step}: the kill did not fire (try {attempt}); running it again", file=sys.stderr)
            continue
        run_id = found.group(1)
        res = subprocess.run([sys.executable, "run.py", "--resume", run_id], cwd=ROOT, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stdout + res.stderr, file=sys.stderr)
        return count(run_id, issue)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--issue", type=int, default=4201)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--only", default=None, help="cases to run, such as after:3,during:5")
    ap.add_argument("--out", default=None)
    ap.add_argument("--count", nargs="*", help="count these run_ids only; run nothing")
    args = ap.parse_args()
    if args.count:
        rows = [count(r, args.issue) for r in args.count]
    else:
        cases = [(w, n) for n in range(1, args.steps + 1) for w in ("after", "during")]
        if args.only:
            wanted = {(c.split(":")[0], int(c.split(":")[1])) for c in args.only.split(",")}
            cases = [c for c in cases if c in wanted]
        rows = []
        for when, step in cases:
            row = one_case(when, step, args.issue, args.backend, args.tries)
            if row:
                rows.append(row)
                print(json.dumps(row), flush=True)
    if args.out:
        path = ROOT / args.out
        old = json.loads(path.read_text()) if path.exists() else []
        path.write_text(json.dumps(old + rows, indent=1) + "\n")
    print(f"{len(rows)} cases; comments {[r['comments'] for r in rows]}; prs {[r['open_prs'] for r in rows]}; "
          f"matches {sum(r['matches'] for r in rows)}/{len(rows)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
