"""Assignment 2's working solution, Part D: the plan against what ran.

A call whose tool_call line names its plan step (`plan_step`, which this
assignment's executor records) belongs to that step, retries and re-runs included.
A call with no plan_step, as in the transcribed runs of fixtures/traces/, matches a
step when it calls the step's tool and agrees with every argument the plan fixes
("$fill" fixes nothing): calls are walked in trace order, and each goes to the
first step, in plan order, that it matches and that no call has claimed yet. So a
second identical call is extra, and slide 53's second run_tests goes to step 5, not 1.
"""

from __future__ import annotations

import json

FILL = "$fill"


def step_args(step: dict) -> dict:
    """A step's arguments, from `args` or from `args_json`."""
    if isinstance(step.get("args"), dict):
        return step["args"]
    try:
        args = json.loads(step.get("args_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return args if isinstance(args, dict) else {}


def tool_calls(trace: list[dict]) -> list[dict]:
    return [r for r in trace if r.get("type") == "tool_call"]


def matches(step: dict, call: dict) -> bool:
    if not step.get("tool") or step["tool"] != call.get("name"):
        return False
    given = call.get("input") or {}
    return all(given.get(k) == v for k, v in step_args(step).items() if v != FILL)


def match(plan: dict, trace: list[dict]) -> tuple[dict, list]:
    """{step id: index of its call in tool_calls(trace)}, and the extra calls' step numbers."""
    steps = plan.get("steps") or []
    claimed: dict = {}
    extra = []
    ids = {str(s.get("id")): s.get("id") for s in steps}
    for index, call in enumerate(tool_calls(trace)):
        if call.get("plan_step") is not None:     # the executor said which step this call ran for
            if str(call["plan_step"]) in ids:
                claimed.setdefault(ids[str(call["plan_step"])], index)
            else:
                extra.append(call.get("step"))
            continue
        for step in steps:
            if step.get("id") not in claimed and matches(step, call):
                claimed[step.get("id")] = index
                break
        else:
            extra.append(call.get("step"))
    return claimed, extra


def diff(plan: dict, trace: list[dict]) -> dict:
    steps = plan.get("steps") or []
    claimed, extra = match(plan, trace)
    labels = {}
    for i, step in enumerate(steps):
        sid = step.get("id")
        if sid not in claimed:
            labels[sid] = "skipped"
        elif any(claimed.get(e.get("id"), -1) > claimed[sid] for e in steps[:i]):
            labels[sid] = "reordered"          # an earlier step's call came after this one's
        else:
            labels[sid] = "executed"
    return {"steps": labels, "extra": extra}
