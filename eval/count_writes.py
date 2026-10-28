"""Assignment 3, Part D, task 4: count what the tracker holds, per arm. Reference solution.

Reads the tracker's database by run_id for each arm's runs (never the traces, which
record what the harness believed), prints the Part D table, and writes the
`writes` object of reports/LAB_03.json (checks/FORMATS.md, section 11.8).

    python -m eval.count_writes
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

from eval.check_triage import check
from harness import LAB, ROOT
from harness.formats import parse_triage_comment
from harness.trace import read_trace
from harness.tracker import Tracker

ARMS = {"harness": {"flaky_writes": True, "readback_fail": False, "key_mode": "derived", "verify": "on"},
        "control": {"flaky_writes": True, "readback_fail": False, "key_mode": "uuid", "verify": "off"}}


def arm_runs(answers: dict) -> dict[str, list[dict]]:
    out = {arm: [] for arm in ARMS}
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_") or path.name.endswith(".calls.jsonl"):
            continue
        records = read_trace(path)
        start, last = records[0], records[-1]
        if start.get("type") != "run_start" or last.get("type") != "run_end":
            continue
        if start.get("lab") != LAB or start.get("way") != "planned" or start.get("issue") not in answers:
            continue
        ends = [r.get("terminal_reason") for r in records if r.get("type") == "end"]
        if set(ends) & {"quota", "rate_limited"}:
            continue
        for arm, switches in ARMS.items():
            if start.get("switches") == switches:
                out[arm].append({"run_id": start["run_id"], "issue": start["issue"], "end": ends[-1] if ends else None})
    return out


def count(runs: list[dict], answers: dict, db: Path) -> dict:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    tracker = Tracker(ROOT, flaky=False, readback_fail=False)
    per_run, prs_right, passes, escalated, committed = [], 0, 0, 0, 0
    for run in runs:
        comments = con.execute("SELECT body FROM comments WHERE run_id = ? AND issue = ? ORDER BY id",
                               (run["run_id"], run["issue"])).fetchall()
        per_run.append(len(comments))
        file = parse_triage_comment(comments[0]["body"])[1] if comments else None
        want = 1 if file not in (None, "none") else 0
        opened = con.execute("SELECT COUNT(*) FROM prs WHERE run_id = ? AND branch = ? AND state = 'open'",
                             (run["run_id"], f"repomind/issue-{run['issue']}")).fetchone()[0]
        others = con.execute("SELECT COUNT(*) FROM prs WHERE run_id = ? AND branch != ?",
                             (run["run_id"], f"repomind/issue-{run['issue']}")).fetchone()[0]
        prs_right += opened == want and not others
        passes += check(tracker, run["run_id"], run["issue"], answers[run["issue"]])
        escalated += run["end"] == "escalated"
        committed += con.execute("SELECT COUNT(*) FROM attempts WHERE run_id = ? AND outcome = 'timeout_after_commit'",
                                 (run["run_id"],)).fetchone()[0]
    con.close()
    return {"runs": len(runs), "comments_per_run_max": max(per_run, default=0),
            "duplicate_comment_runs": sum(1 for n in per_run if n > 1), "prs_correct_runs": prs_right,
            "committed_timeouts": committed, "escalated": escalated, "triage_passes": passes}


def main() -> None:
    answers = {int(k): v for k, v in yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"].items()}
    runs = arm_runs(answers)
    db = ROOT / "tracker" / "tracker.db"
    writes = {arm: count(runs[arm], answers, db) for arm in ARMS}
    rows = [("Runs", "runs"), ("Most triage comments in one run (should be 1)", "comments_per_run_max"),
            ("Runs with a duplicate comment", "duplicate_comment_runs"),
            ("Runs with the right open PRs", "prs_correct_runs"),
            ("Writes that timed out and had committed", "committed_timeouts"),
            ("Runs that ended escalated", "escalated"), ("Triage success", "triage_passes")]
    print(f"{'Measure':<48} {'harness':>8} {'control':>8}")
    for label, key in rows:
        print(f"{label:<48} {writes['harness'][key]:>8} {writes['control'][key]:>8}")
    path = ROOT / "reports" / "LAB_03.json"
    report = json.loads(path.read_text())
    report["writes"] = writes
    path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
