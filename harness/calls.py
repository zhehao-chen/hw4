"""The call record: runs/<run_id>.calls.jsonl, one line per tool call.

Lecture 3, slide 42: every tool call leaves a record, written at the tool boundary
by your registry, independently of what the agent says it did. The runner puts a
CallRecord on every run's context (ctx.calls); your registry writes one line per
attempt of every call, the denied and rejected ones included:

    ctx.calls.write(tool="post_comment", args={...}, plan_step=4, key="9f2c...",
                    attempt=1, outcome="timeout", is_error=True,
                    result="the tracker did not answer in time", latency_s=0.002)

checks/FORMATS.md, section 11.4, defines every field. The writer adds run_id, t
(seconds since the record opened) and role (from tools/roles.yaml), and refuses a
line that lacks a field or names an outcome it does not know.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from harness.roles import role_of

# What happened to one attempt of one call.
OUTCOMES = (
    "ok",         # the tool ran and succeeded
    "error",      # the tool ran and failed: a tool execution error, returned to the model
    "rejected",   # the boundary check refused the arguments: the tool never ran
    "denied",     # a hook denied the call, or raised: the tool never ran
    "timeout",    # a write timed out: it may or may not have happened
    "protocol",   # a protocol error, such as an unknown tool: never shown to the model in detail
)
FIELDS = ("tool", "args", "plan_step", "key", "attempt", "outcome", "is_error", "result", "latency_s", "cost_usd")
RESULT_CHARS = 300


class CallRecord:
    def __init__(self, path: Path, run_id: str, root: Path | None = None):
        self.path = Path(path)
        self.run_id = run_id
        self.root = root
        self._t0 = time.monotonic()
        self._lock = threading.Lock()

    def write(self, *, tool: str, args: dict, outcome: str, is_error: bool, result: str, latency_s: float,
              plan_step=None, key: str | None = None, attempt: int = 1, cost_usd: float = 0.0) -> dict:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}; one of {OUTCOMES} (checks/FORMATS.md, section 11.4)")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError(f"attempt counts from 1, not {attempt!r}")
        line = {"run_id": self.run_id, "t": round(time.monotonic() - self._t0, 3), "tool": tool,
                "role": role_of(tool, self.root), "args": args, "plan_step": plan_step, "key": key,
                "attempt": attempt, "outcome": outcome, "is_error": bool(is_error),
                "result": str(result)[:RESULT_CHARS], "latency_s": round(float(latency_s), 3),
                "cost_usd": float(cost_usd)}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps(line, default=str) + "\n")
        return line


def read_calls(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
