"""Assignment 2's working solution, Parts F and G: build reports/LAB_02.json.

Every field the checker or staff read: `schema` (counted from agent/plan_schema.json;
strict_compiles stays as you set it), `fixture_validation`, `ladder`, `diff_s49`,
`results` for the four configurations from runs/ and the tracker, and `context` for
Part G's runs. Written independently of checks/check_02.py, so that the self-test
compares two implementations rather than one with itself. It also prints Part F's
overhead-by-length line.

    python -m eval.summarize_02
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

import yaml

from agent.detectors import ladder, repeat_check
from agent.diff import diff
from agent.validator import validate
from eval.check_triage import check
from harness import LAB, ROOT
from harness.formats import normalize_path, parse_triage_comment
from harness.trace import read_trace
from harness.tracker import Tracker

CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")
PART_G_ISSUES = (4203, 4204, 4206)   # context is Part G's runs only, never development runs


def _scripted(backend: str) -> bool:
    return backend == "never-stops" or backend.startswith("harness.scripted:")


def configuration(start: dict) -> str | None:
    if start.get("way") == "agent":
        return "agent"
    if start.get("way") == "planned":
        return f"planned_{start.get('critique') or 'off'}"
    return None


def schema_counts(schema: dict) -> dict:
    """Optional fields and union types, by checks/FORMATS.md, section 10.11."""
    defs = schema.get("$defs") or schema.get("definitions") or {}
    optional = unions = 0

    def deref(node):
        while isinstance(node, dict) and "$ref" in node:
            node = defs.get(node["$ref"].split("/")[-1], {})
        return node

    def shapes(node) -> int:
        node = deref(node)
        branches = node.get("anyOf") or node.get("oneOf")
        if branches:
            return len(branches)
        kind = node.get("type")
        return len(set(kind)) if isinstance(kind, list) else 1

    def walk(node, is_field):
        nonlocal optional, unions
        node = deref(node)
        if is_field and shapes(node) > 1:
            unions += 1
        props = node.get("properties") or {}
        optional += len(set(props) - set(node.get("required") or []))
        for child in props.values():
            walk(child, True)
        if isinstance(node.get("items"), dict):
            walk(node["items"], True)
        for branch in node.get("anyOf") or node.get("oneOf") or []:
            walk(branch, False)

    walk(schema, False)
    text = json.dumps(schema)
    representation = "args_json" if '"args_json"' in text else "oneOf"
    return {"args_representation": representation, "optional_fields": optional, "union_types": unions}


def right_answer(body: str | None, answer: dict) -> bool:
    label, file = parse_triage_comment(body or "")
    return label == answer["label"] and file == normalize_path(answer["file"])


def nearest_rank(values: list[float], pct: float) -> float | None:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)] if ordered else None


def results_for(rows_by_config: dict, answers: dict, tracker: Tracker) -> dict:
    out = {}
    for config in CONFIGS:
        rows = rows_by_config[config]
        planned, second = config != "agent", config in ("planned_self", "planned_external")
        sweeps, per_issue = defaultdict(int), {str(i): 0 for i in sorted(answers)}
        tokens, latency, plan_share, critique_share, rounds = [], [], [], [], []
        repeats = off_plan = changed = fixed = broken = held = 0
        revisions = []
        for r in rows:
            start, records = r["start"], r["records"]
            ok = check(tracker, start["run_id"], start["issue"], answers[start["issue"]])
            sweeps[start["sweep"]] += ok
            per_issue[str(start["issue"])] += ok
            calls = [x for x in records if x["type"] == "model_call"]
            prompt = sum(c["usage"]["prompt_tokens"] for c in calls)
            tokens.append(sum(c["usage"]["prompt_tokens"] + c["usage"]["output_tokens"] for c in calls))
            latency.append(records[-1]["elapsed_s"])
            share = lambda purposes: (sum(c["usage"]["prompt_tokens"] for c in calls  # noqa: E731
                                          if c.get("purpose") in purposes) / prompt if prompt else 0.0)
            plan_share.append(share(("plan", "revise")))
            critique_share.append(share(("critique",)))
            repeats += bool(repeat_check(records))
            off_plan += sum(1 for x in records if x["type"] == "off_plan")
            revisions.append(sum(1 for x in records if x["type"] == "revision"))
            lines = [x for x in records if x["type"] == "critique"]
            rounds.append(len(lines))
            if lines and any(x["changed"] for x in lines):
                changed += 1
                before = right_answer(lines[0]["draft"], answers[start["issue"]])
                fixed += (not before) and ok
                broken += before and not ok
            held += bool(lines) and lines[-1]["result"] == "fail" and not tracker.comments(run_id=start["run_id"])
        n = len(rows)
        mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        out[config] = {
            "runs": n, "passes": sum(per_issue.values()), "per_issue": per_issue,
            "sweep_min": min(sweeps.values()) if sweeps else None,
            "sweep_max": max(sweeps.values()) if sweeps else None,
            "mean_tokens": mean(tokens), "p50_latency_s": nearest_rank(latency, 50),
            "max_latency_s": max(latency, default=None),
            "plan_overhead_share": mean(plan_share) if planned else None,
            "critique_overhead_share": mean(critique_share) if second else None,
            "runs_with_repeat": repeats,
            "off_plan": off_plan if planned else None,
            "revisions_mean": mean(revisions) if planned else None,
            "revisions_max": max(revisions, default=None) if planned else None,
            "rounds_mean": mean(rounds) if second else None,
            "rounds_max": max(rounds, default=None) if second else None,
            "drafts_changed": changed if second else None,
            "drafts_fixed": fixed if second else None,
            "drafts_broken": broken if second else None,
            "drafts_held": held if second else None,
        }
        if config == "planned_off" and rows:
            by_length = defaultdict(list)
            for r, s in zip(rows, plan_share):
                length = sum(1 for x in r["records"] if x["type"] == "model_call")
                by_length["up to 4 model calls" if length <= 4 else "5 or more"].append(s)
            print("plan overhead by run length:",
                  {k: f"{sum(v) / len(v):.0%} over {len(v)} runs" for k, v in sorted(by_length.items())})
    return out


def context_for(rows: list[dict]) -> list[dict]:
    """Part G: each run's questions, scored against its own tool_call lines."""
    out = []
    for r in rows:
        start, records = r["start"], r["records"]
        seen, compacted, first_question, questions = set(), False, None, []
        for x in records:
            if x["type"] == "tool_call":
                seen.update(x.get("paths") or [])
            elif x["type"] == "compaction" and first_question is None:
                compacted = True
            elif x["type"] == "question":
                first_question = first_question or x
                questions.append({"path": x["path"], "truth": "yes" if x["path"] in seen else "no",
                                  "answer": x["answer"]})
        out.append({"run_id": start["run_id"], "issue": start["issue"], "notes_shown": start.get("notes") == "on",
                    "compacted": compacted, "questions": questions,
                    "right": sum(q["truth"] == q["answer"] for q in questions)})
    return out


def main() -> None:
    answers = {int(k): v for k, v in yaml.safe_load((ROOT / "fixtures/answers.yaml").read_text())["eval"].items()}
    tracker = Tracker(ROOT)
    by_config = {c: [] for c in CONFIGS}
    notes_runs = []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        start, end = records[0], records[-1]
        if start.get("lab") != LAB or end.get("type") != "run_end" or _scripted(start.get("backend", "")):
            continue
        if any(r.get("type") == "end" and r.get("terminal_reason") in ("quota", "rate_limited") for r in records):
            continue                              # stopped by the daily quota or a rate limit: not finished
        if start.get("way") == "notes" and start.get("issue") in PART_G_ISSUES:
            notes_runs.append({"start": start, "records": records})
        elif start.get("way") != "notes" and configuration(start) in CONFIGS and start.get("issue") in answers:
            by_config[configuration(start)].append({"start": start, "records": records})

    report_path = ROOT / "reports" / "LAB_02.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    strict = (report.get("schema") or {}).get("strict_compiles")
    report["lab"] = LAB
    report["schema"] = {**schema_counts(json.loads((ROOT / "agent/plan_schema.json").read_text())),
                        "strict_compiles": strict}
    report["fixture_validation"] = [
        {"plan": p.name, **validate(json.loads(p.read_text()))} for p in sorted((ROOT / "fixtures/plans").glob("*.json"))]
    report["ladder"] = {}
    for run in ("looping", "s49"):
        folder = ROOT / "fixtures" / "traces" / run
        plan, trace = json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl")
        report["ladder"][run] = {q: {"fired": v["fired"], "ids": v["ids"]} for q, v in ladder(plan, trace).items()}
        if run == "s49":
            d = diff(plan, trace)
            report["diff_s49"] = {"steps": {str(k): v for k, v in d["steps"].items()}, "extra": d["extra"]}
    report["results"] = results_for(by_config, answers, tracker)
    report["context"] = context_for(notes_runs)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({c: {k: report["results"][c][k] for k in ("runs", "passes", "sweep_min", "sweep_max")}
                      for c in CONFIGS}))
    print("context:", [(e["issue"], e["notes_shown"], e["right"]) for e in report["context"]])


if __name__ == "__main__":
    main()
