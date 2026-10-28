"""Assignment 2's working solution, Part D: three detectors and the ladder.

    python -m agent.detectors                  # both runs in fixtures/traces/
"""

from __future__ import annotations

import json

from agent.diff import match, tool_calls


def _key(call: dict) -> str:
    return json.dumps([call.get("name"), call.get("input") or {}], sort_keys=True)


def repeat_check(trace: list[dict]) -> list[list]:
    """Exact repeats: the same tool with the same arguments. Groups of step numbers."""
    groups: dict[str, list] = {}
    for call in tool_calls(trace):
        groups.setdefault(_key(call), []).append(call.get("step"))
    return [steps for steps in groups.values() if len(steps) > 1]


def orphan_check(plan: dict) -> list:
    """Steps, other than the last, that no later step lists in depends_on."""
    steps = plan.get("steps") or []
    used = set()
    for step in steps:
        used.update(str(d) for d in step.get("depends_on") or [])
    return [s.get("id") for s in steps[:-1] if str(s.get("id")) not in used]


def expected_result_check(plan: dict, trace: list[dict]) -> list:
    """Steps that did not run and return their result: never matched, or matched to an error."""
    calls = tool_calls(trace)
    claimed, _ = match(plan, trace)
    return [s.get("id") for s in plan.get("steps") or []
            if s.get("id") not in claimed or calls[claimed[s.get("id")]].get("is_error")]


def _unused_from_trace(trace: list[dict]) -> list:
    """Question 2 without depends_on: a call whose result was fetched again, not used."""
    return [group[0] for group in repeat_check(trace)]


def ladder(plan: dict, trace: list[dict]) -> dict:
    has_dependencies = any("depends_on" in s for s in plan.get("steps") or [])
    q1 = repeat_check(trace)
    q2 = orphan_check(plan) if has_dependencies else _unused_from_trace(trace)
    q3 = expected_result_check(plan, trace)
    return {"q1": {"fired": bool(q1), "ids": q1},
            "q2": {"fired": bool(q2), "ids": q2, "from": "plan" if has_dependencies else "trace"},
            "q3": {"fired": bool(q3), "ids": q3}}


if __name__ == "__main__":
    from agent.diff import diff
    from harness import ROOT
    from harness.trace import read_trace

    for run in ("looping", "s49"):
        folder = ROOT / "fixtures" / "traces" / run
        plan, trace = json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl")
        print(run, json.dumps(ladder(plan, trace)), json.dumps(diff(plan, trace)))
