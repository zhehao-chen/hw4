"""Assignment 1, Part A: the bounded loop, as Assignment 1's working solution writes it.

The smallest tool-using loop that meets the contract: three bounds checked in
code before every call, one trace line per model call and per tool call, one
terminal reason written by the harness.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.client import tool_result


@dataclass(frozen=True)
class Bounds:
    max_steps: int
    max_tokens: int
    wall_clock_s: float


def load_bounds(path: Path | str = Path(__file__).parent / "bounds.yaml") -> Bounds:
    data = yaml.safe_load(Path(path).read_text())
    return Bounds(int(data["max_steps"]), int(data["max_tokens"]), float(data["wall_clock_s"]))


def run_loop(client, tools, system: str, user_message: str, bounds: Bounds, trace) -> str:
    messages = [{"role": "user", "content": user_message}]
    started = time.monotonic()
    last_text = ""
    step = 0
    while True:
        # The bounds are checked here, in code, before every call. The model is never asked.
        if step >= bounds.max_steps:
            trace.end("turn_limit", detail=f"{step} model calls")
            return last_text
        if client.total_tokens >= bounds.max_tokens:
            trace.end("token_budget", detail=f"{client.total_tokens} tokens")
            return last_text
        if time.monotonic() - started >= bounds.wall_clock_s:
            trace.end("wall_clock", detail=f"{time.monotonic() - started:.1f}s")
            return last_text

        step += 1
        response = client.create(system=system, messages=messages, tools=tools.schemas)
        trace.model_call(step, response)
        last_text = response.text or last_text

        # Act on every tool call the model returned, whatever stop_reason says: a model
        # can return a call with stop_reason end_turn. Stop only when there are none.
        if not response.tool_calls:
            trace.end("refusal" if response.stop_reason == "refusal" else "model_stopped",
                      detail=response.stop_reason)
            return last_text

        messages.append(response.assistant_message())
        results = []
        for call in response.tool_calls:
            try:
                result = tools.call(call.name, call.input)
            except Exception as exc:  # a tool that raises, rather than reporting an error
                trace.end("tool_error", detail=f"{call.name}: {exc}")
                return last_text
            trace.tool_call(step, call, result)
            results.append(tool_result(call, result.content, result.is_error))
        messages.append({"role": "user", "content": results})
