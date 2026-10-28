"""The run trace: runs/<run_id>.jsonl, one JSON object per line.

The runner writes the first line (run_start) and the last (run_end). Your code
writes everything in between: call trace.model_call after every model call,
trace.tool_call after every tool call, and, in the agent's loop, trace.end
exactly once with the reason the loop stopped. checks/FORMATS.md has the
fields; the checker reads nothing else.

Assignment 2 adds these (checks/FORMATS.md, section 10):

    trace.model_call(step, response, purpose="plan")   # or "revise", "execute", "critique"
    trace.plan(version, plan)                           # a plan line: the plan as data
    trace.event("off_plan", step=..., tool=...)         # an event line of the kind named
    trace.event("revision", checkpoint=..., version=..., valid=...)
    trace.event("critique", round=..., mode=..., result=..., reason=..., changed=..., draft=...)
    trace.event("compaction", threshold=..., tokens=...)
    trace.event("question", path=..., answer=...)
    trace.event("schema", errors=[...])

`paths` and `plan_step` on every tool_call line (the files the call returned, and
the plan step it ran for: ctx.call_tool(step, name, input, plan_step=id)), and two
terminal reasons: escalated, for a run that hands the issue to a person, and quota,
which the runner writes when the vendor's daily quota stops a run.

Assignment 3 adds `tools` on every model_call line: the names of the tools that
call's request carried (checks/FORMATS.md, section 11.10). Part D prices them.

Assignment 4 adds two kinds of event, and the resume line (checks/FORMATS.md,
section 12):

    trace.event("checkpoint", step=..., mode="sync")    # a checkpoint saved: its plan step, its mode
    trace.event("store_read", issue=..., records=[...]) # a read of the memory store, the IDs returned

On a development issue, 4191 or 4192, every model_call line also carries `request`,
the call's number in the request record, runs/<run_id>.requests.jsonl, which the
harness writes (section 12.10): Part F reads what each call was sent from there.

A run killed by run.py --die-after-step or --die-during-step has no run_end line.
`python run.py --resume <run_id>` reopens its trace and goes on after a resume
line, so one file holds both halves of the run.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from harness.formats import DURABILITY_MODES, EVENT_FIELDS, PURPOSES, RESERVED_TYPES, TERMINAL_REASONS, result_paths


class TraceWriter:
    def __init__(self, path: Path, run_id: str, meta: dict, *, resume: bool = False):
        """A new trace starts with run_start. With resume=True (run.py --resume), the
        crashed run's trace is reopened and goes on after a resume line carrying `meta`."""
        self.path = Path(path)
        self.run_id = run_id
        self._t0 = time.monotonic()
        self._lock = threading.Lock()
        self._ended = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a" if resume else "w")
        self._write({"type": "resume" if resume else "run_start", **meta})

    def _write(self, record: dict) -> None:
        record = {"run_id": self.run_id, "t": round(time.monotonic() - self._t0, 3), **record}
        with self._lock:
            self._fh.write(json.dumps(record, default=str) + "\n")
            self._fh.flush()

    # -- for your code ----------------------------------------------------------------
    def model_call(self, step: int, response, purpose: str | None = None) -> None:
        """Record one model call. `response` is what ModelClient.create returned.

        `purpose` says what the call was for: "plan" (the planner), "revise" (the
        reviser), "execute" (the executor filling in a step) or "critique" (the
        second pass: a self critique, or a rewrite of the draft), or None."""
        if purpose is not None and purpose not in PURPOSES:
            raise ValueError(f"unknown purpose {purpose!r}; use one of {PURPOSES} or None")
        self._write({
            "type": "model_call",
            "step": step,
            "purpose": purpose,
            "model": response.model,
            "stop_reason": response.stop_reason,
            "latency_s": round(response.latency_s, 3),
            "usage": response.usage.as_dict(),
            "cost_usd": response.cost_usd,
            "tool_calls": [{"name": c.name, "input": c.input} for c in response.tool_calls],
            "tools": list(getattr(response, "offered", None) or []),
            "request": getattr(response, "request", None),
            "text": response.text[:2000],
        })

    def tool_call(self, step: int, call, result, plan_step=None) -> None:
        """Record one tool call. `call` is a ToolCall; `result` is what ToolRegistry.call returned.

        `plan_step` is the id of the plan step the executor is running, or None
        outside a plan (Assignment 1's ways). ctx.call_tool passes it on."""
        self._write({
            "type": "tool_call",
            "step": step,
            "plan_step": plan_step,
            "name": call.name,
            "input": call.input,
            "is_error": result.is_error,
            "latency_s": round(result.latency_s, 3),
            "result_chars": len(result.content),
            "result_excerpt": result.content[:300],
            "paths": result_paths(call.name, call.input, result.content, result.is_error),
        })

    def plan(self, version: int, plan: dict) -> None:
        """Record a version of the plan, as data, before any of its steps runs.

        Version 1 comes before the run's first tool call. Log a revision only once
        it has passed your validator; a rejected one gets a revision event instead."""
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError(f"plan version must be an integer from 1, not {version!r}")
        if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
            raise ValueError("a plan is a dict with a 'steps' list (checks/FORMATS.md, section 10.1)")
        self._write({"type": "plan", "version": version, "plan": plan})

    def event(self, kind: str, **fields) -> None:
        """Record an event line whose type is `kind`, with any fields you give it.

        Assignment 2 names six kinds, each with fields it must carry:
            off_plan     step, tool                          a call your executor refused
            revision     checkpoint, version, valid          an attempt to revise the plan
            critique     round, mode, result, reason, changed, draft    one round of the second pass
            compaction   threshold, tokens                   older turns replaced by a summary
            question     path, answer                        Part G: "Has this run seen <path>?"
            schema       errors                              a plan that broke agent/plan_schema.json
        Assignment 4 names two more:
            checkpoint   step, mode                          a checkpoint saved; mode is sync, async or exit
            store_read   issue, records                      a read of the memory store, the record IDs it returned
        Other kinds are yours, as long as they are not a line type the harness writes."""
        if not isinstance(kind, str) or not kind.isidentifier():
            raise ValueError(f"event kind must be a plain name such as 'off_plan', not {kind!r}")
        if kind in RESERVED_TYPES:
            raise ValueError(f"{kind!r} is a line the harness writes; use trace.{kind}() or another kind")
        clash = {"run_id", "t", "type"} & set(fields)
        if clash:
            raise ValueError(f"event fields may not be named {sorted(clash)}")
        missing = [f for f in EVENT_FIELDS.get(kind, ()) if f not in fields]
        if missing:
            raise ValueError(f"a {kind} event needs {missing} (checks/FORMATS.md, sections 10.4 and 12.3)")
        if kind == "checkpoint" and fields["mode"] not in DURABILITY_MODES:
            raise ValueError(f"a checkpoint's mode is one of {DURABILITY_MODES}, not {fields['mode']!r}")
        if kind == "store_read" and not isinstance(fields["records"], list):
            raise ValueError("a store_read event's records is a list of the record IDs the read returned")
        self._write({"type": kind, **fields})

    def end(self, terminal_reason: str, detail: str = "") -> None:
        """Record why the run stopped. Call it once, from your harness code, never from the model's words."""
        if terminal_reason not in TERMINAL_REASONS:
            raise ValueError(f"unknown terminal_reason {terminal_reason!r}; see harness.formats.TERMINAL_REASONS")
        if self._ended:
            raise RuntimeError("trace.end() was already called for this run")
        self._ended = True
        self._write({"type": "end", "terminal_reason": terminal_reason, "detail": detail})

    # -- for the runner ---------------------------------------------------------------
    @property
    def ended(self) -> bool:
        return self._ended

    def close(self) -> None:
        """Close the file without a run_end line (tests, and checks that only write a few lines)."""
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def run_end(self, totals: dict, error: str | None) -> None:
        if not self._ended:
            self.end("crashed" if error else "completed",
                     detail="written by the runner" + ("; your way raised, see run_end.error" if error else ""))
        self._write({"type": "run_end", "elapsed_s": round(time.monotonic() - self._t0, 3),
                     "totals": totals, "error": error})
        self.close()


def read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
