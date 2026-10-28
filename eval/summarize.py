"""Assignment 1's results script: builds reports/LAB_01.json from runs/ and the tracker.

It decides each run's success with eval/check_triage.check, and computes every
field of checks/FORMATS.md, section 7, from the traces.

    python -m eval.summarize --A 440 --F <first prompt tokens>
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from eval.check_triage import check
from eval.part0 import part0
from harness import ROOT
from harness.trace import read_trace
from harness.tracker import Tracker

WAYS = ("direct", "workflow", "agent", "hybrid")


def nearest_rank(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--F", type=float, required=True)
    p.add_argument("--A", type=float, required=True)
    a = p.parse_args()

    answers = {int(k): v for k, v in yaml.safe_load((ROOT / "fixtures/answers.yaml").read_text())["eval"].items()}
    tracker = Tracker(ROOT)
    by_way = defaultdict(list)
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        start, end = records[0], records[-1]
        if start.get("way") in WAYS and start["issue"] in answers and end["type"] == "run_end" \
                and start["backend"] != "never-stops":
            calls = [r for r in records if r["type"] == "model_call"]
            by_way[start["way"]].append({
                "issue": start["issue"], "sweep": start["sweep"], "run_id": start["run_id"],
                "ok": check(tracker, start["run_id"], start["issue"], answers[start["issue"]]),
                "prompt": sum(c["usage"]["prompt_tokens"] for c in calls),
                "output": sum(c["usage"]["output_tokens"] for c in calls),
                "cached": sum(c["usage"]["cache_read_input_tokens"] for c in calls),
                "cost": sum(c["cost_usd"] or 0 for c in calls),
                "latency": end["elapsed_s"],
                "tools": [r["name"] for r in records if r["type"] == "tool_call"],
                # the runner ends a run with "completed" only when no loop ended it
                "handoff": any(r["type"] == "end" and r["terminal_reason"] != "completed" for r in records),
            })

    results = {}
    for way in WAYS:
        runs = by_way[way]
        per_issue = {str(i): sum(r["ok"] for r in runs if r["issue"] == i) for i in sorted(answers)}
        runs_per_issue = Counter(r["issue"] for r in runs)
        sweeps = defaultdict(int)
        for r in runs:
            sweeps[r["sweep"]] += r["ok"]
        n = len(runs) or 1
        results[way] = {
            "runs": len(runs),
            "passes": sum(r["ok"] for r in runs),
            "per_issue": per_issue,
            "sweep_min": min(sweeps.values()) if sweeps else None,
            "sweep_max": max(sweeps.values()) if sweeps else None,
            "all_ten": sum(1 for i in answers if runs_per_issue[i] >= 10 and per_issue[str(i)] == runs_per_issue[i]),
            "mean_prompt_tokens": sum(r["prompt"] for r in runs) / n,
            "mean_output_tokens": sum(r["output"] for r in runs) / n,
            "mean_cached_tokens": sum(r["cached"] for r in runs) / n,
            "p50_latency_s": nearest_rank([r["latency"] for r in runs], 50),
            "p95_latency_s": nearest_rank([r["latency"] for r in runs], 95),
            "mean_cost_usd": sum(r["cost"] for r in runs) / n,
            "mean_tool_calls": sum(len(r["tools"]) for r in runs) / n,
            "max_tool_calls": max((len(r["tools"]) for r in runs), default=0),
        }

    direct, workflow, agent = (results[w] for w in ("direct", "workflow", "agent"))
    wf_pass = {i: sum(r["ok"] for r in by_way["workflow"] if r["issue"] == i) for i in answers}
    ag_pass = {i: sum(r["ok"] for r in by_way["agent"] if r["issue"] == i) for i in answers}
    f = sum(1 for i in answers if wf_pass[i] < 5 and ag_pass[i] >= 5) / len(answers)
    m = agent["mean_cost_usd"] / workflow["mean_cost_usd"] if workflow["mean_cost_usd"] else None
    c = workflow["mean_cost_usd"]
    sequences = Counter(tuple(r["tools"]) for r in by_way["agent"])
    top3 = sum(count for _, count in sequences.most_common(3))

    n_steps = int(yaml.safe_load((ROOT / "agent/bounds.yaml").read_text())["max_steps"])
    report = {
        "lab": "01",
        "part0": part0(),
        "worst_case": {"F": a.F, "A": a.A, "N": n_steps,
                       "cumulative_prompt_tokens": n_steps * a.F + a.A * n_steps * (n_steps - 1) / 2},
        "results": results,
        "analysis": {
            "ratio_agent_over_direct_tokens": (agent["mean_prompt_tokens"] + agent["mean_output_tokens"])
            / max(1, direct["mean_prompt_tokens"] + direct["mean_output_tokens"]),
            "m_agent_over_workflow_cost": m,
            "f": f,
            "blended_cost": c * ((1 - f) + f * m) if m is not None else None,
            "all_agent_cost": c * m if m is not None else None,
            "workflow_cost": c,
            "path_entropy": {"distinct_sequences": len(sequences),
                             "top3_share": top3 / max(1, sum(sequences.values()))},
            "verdict": "fill in from the numbers",
            "hybrid_handoffs": sum(r["handoff"] for r in by_way["hybrid"]),
        },
    }
    (ROOT / "reports/LAB_01.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({w: {k: results[w][k] for k in ("runs", "passes", "sweep_min", "sweep_max")} for w in WAYS}))


if __name__ == "__main__":
    main()
