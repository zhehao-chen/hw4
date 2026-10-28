"""The metered model client.

Every model call in every assignment goes through ModelClient.create. It times the
call, prices it from pricing.yaml, keeps running totals, and refuses to start a
call once the run's hard ceiling (settings.session_token_ceiling) is reached.

That ceiling is the course's backstop, not your loop's token budget: your loop
enforces its own, lower budget (Assignment 1, Part A) and ends the run cleanly first.

Messages use one format whatever your vendor: a list of {"role", "content"}
dicts, where an assistant turn's content is exactly `response.content` (keep
every block, including thinking blocks, unchanged) and tool results go back in
one user turn built with tool_result(). The backend translates for its API
(harness/backends.py), so your code never changes when your model does.

Assignment 3 adds `offered` to every response: the names of the tools its request
carried, which the trace's model_call line records as `tools` (Part D prices them).

Assignment 4 adds the request record, for Part F. On a development issue, 4191 or
4192, the runner gives the client runs/<run_id>.requests.jsonl, and every request
is written there, numbered from 1, before it is sent: the system prompt, the
messages and the names of the tools offered. The response carries its number as
`request`, which the trace's model_call line records, so the checker can read what
a call was sent (checks/FORMATS.md, section 12.10). A resumed run's record goes on
from its last number.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """The run hit the harness's hard token ceiling. The runner records it and moves on."""


@dataclass
class Usage:
    input_tokens: int = 0                 # uncached input, full price
    output_tokens: int = 0                # includes any thinking tokens
    cache_read_input_tokens: int = 0      # input served from cache
    cache_creation_input_tokens: int = 0  # input written to cache
    cache_creation_1h_tokens: int = 0     # the part of the write that used the 1-hour TTL

    @property
    def prompt_tokens(self) -> int:
        """Everything the model read on this call: uncached, cache reads and cache writes."""
        return self.input_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "prompt_tokens": self.prompt_tokens,
        }


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelResponse:
    content: list[dict]      # every block the model returned; append it unchanged
    stop_reason: str         # end_turn | tool_use | max_tokens | refusal | pause_turn | ...
    model: str               # the model that actually served the call
    usage: Usage
    latency_s: float
    cost_usd: float | None   # None when the served model is not on the price sheet
    offered: list[str] = field(default_factory=list)   # the names of the tools the request carried
    request: int | None = None   # its number in runs/<run_id>.requests.jsonl, on a development issue

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [
            ToolCall(id=b["id"], name=b["name"], input=b.get("input") or {})
            for b in self.content
            if b.get("type") == "tool_use"
        ]

    @property
    def text(self) -> str:
        return "\n".join(b.get("text", "") for b in self.content if b.get("type") == "text").strip()

    def assistant_message(self) -> dict:
        """The assistant turn to append to your messages before sending tool results."""
        return {"role": "assistant", "content": self.content}


def tool_result(call: ToolCall, content: str, is_error: bool = False) -> dict:
    """One tool_result block. Send all of a step's results together in one user turn."""
    block = {"type": "tool_result", "tool_use_id": call.id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


@dataclass
class _Totals:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    models: set = field(default_factory=set)


class ModelClient:
    def __init__(self, backend, prices, *, session_ceiling: int | None = None,
                 requests: Path | None = None, run_id: str | None = None):
        self.backend = backend
        self.prices = prices
        self.session_ceiling = session_ceiling
        self._totals = _Totals()
        self._lock = threading.Lock()
        self.requests = Path(requests) if requests else None   # the request record, or None
        self.run_id = run_id
        self._sent = 0
        if self.requests is not None and self.requests.exists():   # a resume goes on from the last number
            self._sent = sum(1 for line in self.requests.read_text().splitlines() if line.strip())

    def _record(self, system, messages, tools) -> int | None:
        """Write one request to the request record before it is sent; its number."""
        if self.requests is None:
            return None
        with self._lock:
            self._sent += 1
            line = {"run_id": self.run_id, "n": self._sent, "system": system, "messages": messages,
                    "tools": [str(t.get("name")) for t in tools or []]}
            self.requests.parent.mkdir(parents=True, exist_ok=True)
            with self.requests.open("a") as fh:
                fh.write(json.dumps(line, default=str) + "\n")
            return self._sent

    # -- the one call -----------------------------------------------------------
    def create(self, *, messages: list[dict], system: str | None = None,
               tools: list[dict] | None = None) -> ModelResponse:
        if self.session_ceiling is not None and self.total_tokens >= self.session_ceiling:
            raise BudgetExceeded(
                f"harness ceiling reached: {self.total_tokens} >= {self.session_ceiling} tokens this run"
            )
        number = self._record(system, messages, tools)
        start = time.monotonic()
        content, stop_reason, model, usage = self.backend.create(
            system=system, messages=messages, tools=tools or None
        )
        latency = time.monotonic() - start
        cost = self.prices.cost(model, usage)
        with self._lock:
            t = self._totals
            t.calls += 1
            t.prompt_tokens += usage.prompt_tokens
            t.output_tokens += usage.output_tokens
            t.cache_read_tokens += usage.cache_read_input_tokens
            t.models.add(model)
            if cost is None:
                t.unpriced_calls += 1
            else:
                t.cost_usd += cost
        return ModelResponse(content, stop_reason, model, usage, latency, cost,
                             [str(t.get("name")) for t in tools or []], number)

    # -- running totals for this run ------------------------------------------------
    @property
    def calls(self) -> int:
        return self._totals.calls

    @property
    def prompt_tokens(self) -> int:
        return self._totals.prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self._totals.output_tokens

    @property
    def total_tokens(self) -> int:
        return self._totals.prompt_tokens + self._totals.output_tokens

    @property
    def cost_usd(self) -> float:
        return self._totals.cost_usd

    def totals(self) -> dict:
        t = self._totals
        return {
            "model_calls": t.calls,
            "prompt_tokens": t.prompt_tokens,
            "output_tokens": t.output_tokens,
            "cache_read_tokens": t.cache_read_tokens,
            "total_tokens": t.prompt_tokens + t.output_tokens,
            "cost_usd": round(t.cost_usd, 6),
            "unpriced_calls": t.unpriced_calls,
            "models": sorted(t.models),
        }
