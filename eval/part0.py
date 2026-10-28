"""Assignment 1, Part 0: read the recorded run.

    python -m eval.part0
"""

from __future__ import annotations

import json
from pathlib import Path

from harness import ROOT


def part0(path: Path = ROOT / "fixtures" / "week01_recorded_run.jsonl") -> dict:
    calls, tool_calls = {}, 0
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if event.get("type") == "assistant":
            message = event["message"]
            calls[message["id"]] = message.get("usage", {})  # one call can span several lines
            tool_calls += sum(1 for b in message.get("content", []) if b.get("type") == "tool_use")
    usages = list(calls.values())

    def prompt(u):
        return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)

    total = sum(prompt(u) for u in usages)
    cached = sum(u.get("cache_read_input_tokens", 0) for u in usages)
    return {"model_calls": len(usages), "tool_calls": tool_calls, "prompt_tokens": total,
            "cache_read_tokens": cached, "cache_read_share": round(cached / total, 4),
            "first_prompt": prompt(usages[0]), "last_prompt": prompt(usages[-1]),
            "cumulative_over_first": round(total / prompt(usages[0]), 2)}


if __name__ == "__main__":
    print(json.dumps(part0(), indent=2))
