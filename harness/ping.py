"""Check your model before you spend anything real: `make ping`.

Three tiny calls through the same client and backend your ways use. The first
offers one tool and asks the model to call it; the second sends the tool's result
back and asks for a one-word answer. Together they prove the four things the
assignment depends on: your key works, the model is the one you chose, it calls
tools, and pricing.yaml has its line.

The third is Assignment 3's live test of your definitions (Part A, tasks 5 and 7):
one request carrying all five, exactly as your registry sends them (its
`schemas`), with "strict" where you set it. A vendor that refuses a schema refuses
the request, and ping prints the vendor's words. Every try is recorded in
runs/_ping.jsonl, with a hash of the definitions it sent; the checker reads the
latest accepted try whose definitions are the ones in tools/ now (checks/FORMATS.md,
section 11.6). Change a definition, and run `make ping` again.

    python -m harness.ping                                    # make ping
    python -m harness.ping --backend harness.scripted:ScriptedTriage   # the plumbing, free; the checker ignores it
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time

from harness import ROOT
from harness.backends import REAL_BACKENDS, make_backend
from harness.client import ModelClient, tool_result
from harness.pricing import PriceSheet
from harness.settings import load_settings

ECHO = {"name": "echo", "description": "Return the text you give it.",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}
SYSTEM = "You are a connectivity test."
RECORD = ROOT / "runs" / "_ping.jsonl"


def definitions_hash(schemas: list[dict]) -> str:
    """The hash runs/_ping.jsonl records, of the definitions exactly as sent."""
    return hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()[:16]


def current_schemas() -> list[dict]:
    """Your five definitions, as your registry sends them."""
    from tools import RunContext, default_tools
    return default_tools(RunContext(run_id="ping", tracker=None, repo_root=ROOT / "fixtures" / "repo")).schemas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", help="a scripted backend instead of settings.yaml's provider (tests the plumbing)")
    a = p.parse_args(argv)
    settings = load_settings(ROOT / "settings.yaml")
    backend_name = a.backend or settings.provider
    if not a.backend and (settings.provider not in REAL_BACKENDS or not settings.model):
        print("settings.yaml: set provider (anthropic or openai-compatible) and model first.")
        return 1
    print(f"provider {backend_name}" + (f", model {settings.model}" if backend_name in REAL_BACKENDS else "")
          + (f", base_url {settings.base_url}" if settings.base_url and backend_name in REAL_BACKENDS else ""))
    try:
        client = ModelClient(make_backend(backend_name, settings), PriceSheet(ROOT / "pricing.yaml"))
        problems = _ping(client)
    except Exception as exc:  # the vendor's own words say what is wrong: key, model name, or endpoint
        print(f"PROBLEM: the call failed: {type(exc).__name__}: {str(exc)[:600]}")
        print("not ready")
        return 1
    problems += _definitions(client, backend_name, settings)
    t = client.totals()
    real = backend_name in REAL_BACKENDS
    print(f"tokens: {t['prompt_tokens']} prompt, {t['output_tokens']} output; "
          + ("cost: none, a scripted model" if not real
             else f"cost ${t['cost_usd']:.6f}" if not t["unpriced_calls"] else "cost: UNPRICED"))
    if t["unpriced_calls"] and real:
        problems.append(f"pricing.yaml has no line for {sorted(t['models'])}: add one, with its source and the date you read it")
    for problem in problems:
        print(f"PROBLEM: {problem}")
    if not real and not problems:
        print("the plumbing works; a scripted model is not your vendor, so the checker counts only a ping "
              "from your model")
    print("ready" if not problems else "not ready")
    return 1 if problems else 0


def _ping(client) -> list[str]:
    messages = [{"role": "user", "content": "Call the echo tool once with the text 'ping'. Do not answer in words."}]
    first = client.create(system=SYSTEM, messages=messages, tools=[ECHO])
    calls = first.tool_calls
    print(f"1. served by {first.model}; stop_reason {first.stop_reason}; "
          f"tool calls {[(c.name, c.input) for c in calls] or 'none'}")
    if not calls:
        return ["the model did not call the tool: RepoMind needs a model with tool calling"]
    messages += [first.assistant_message(), {"role": "user", "content": [tool_result(calls[0], "ping")]}]
    second = client.create(system=SYSTEM + " Answer in one word.", messages=messages, tools=[ECHO])
    print(f"2. stop_reason {second.stop_reason}; answer {second.text[:60]!r}")
    return []


def _definitions(client, backend_name: str, settings) -> list[str]:
    """The third call: all five definitions in one request. Recorded either way."""
    try:
        schemas = current_schemas()
    except Exception as exc:
        print(f"3. your definitions could not be loaded: {type(exc).__name__}: {exc}")
        return ["tools/*.json or tools/__init__.py is broken: the registry could not be built"]
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "backend": backend_name,
            "model": settings.model if backend_name in REAL_BACKENDS else backend_name,
            "tools": [s.get("name") for s in schemas], "strict": {s.get("name"): s.get("strict") for s in schemas},
            "definitions": definitions_hash(schemas), "accepted": False, "served_by": None, "error": None}
    problems = []
    try:
        reply = client.create(system=SYSTEM, tools=schemas,
                              messages=[{"role": "user", "content": "Do not call any tool. Answer with the word ok."}])
        line.update(accepted=True, served_by=reply.model)
        strict = sum(1 for s in schemas if s.get("strict"))
        print(f"3. your {len(schemas)} definitions were accepted in one request ({strict} marked strict)")
    except Exception as exc:
        line["error"] = f"{type(exc).__name__}: {str(exc)[:600]}"
        print(f"3. your definitions were refused: {line['error']}")
        problems.append("the vendor refused a request carrying your five definitions: its words are above")
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    with RECORD.open("a") as fh:
        fh.write(json.dumps(line) + "\n")
    return problems


if __name__ == "__main__":
    sys.exit(main())
