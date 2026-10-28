"""Assignment 2's working solution, Part B: the four checks.

About thirty lines, as Lecture 2, slide 18 promises. Positions, not id values, decide
what "earlier" means, so a plan may number its steps however it likes.
"""

from __future__ import annotations

from agent.loop import load_bounds


def validate(plan: dict, max_steps: int | None = None) -> dict:
    steps = plan.get("steps") or []
    tools = set((plan.get("meta") or {}).get("tools") or [])
    limit = load_bounds().max_steps if max_steps is None else max_steps
    position: dict[str, int] = {}
    for i, step in enumerate(steps):
        position.setdefault(str(step.get("id")), i)

    failures = []
    for i, step in enumerate(steps):
        sid, tool = step.get("id"), step.get("tool")
        if tool and tool not in tools:                                            # 1: the tool exists
            failures.append({"step": sid, "check": 1})
        if any(position.get(str(d), len(steps)) >= i for d in step.get("depends_on") or []):
            failures.append({"step": sid, "check": 2})                            # 2: only earlier steps
        if not tool or not str(step.get("expected_result") or "").strip():       # 3: an observable outcome
            failures.append({"step": sid, "check": 3})
    if not 1 <= len(steps) <= limit:                                              # 4: within bounds
        failures.append({"step": None, "check": 4})
    return {"valid": not failures, "failures": failures}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    for name in sys.argv[1:] or sorted(str(p) for p in Path("fixtures/plans").glob("*.json")):
        print(Path(name).name, json.dumps(validate(json.loads(Path(name).read_text()))))
