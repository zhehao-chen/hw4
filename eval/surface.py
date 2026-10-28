"""Assignment 3, Part D, task 1: price the tool surface. Reference solution.

    python -m eval.surface                        # the starter's definitions from tag lab-03-start
    python -m eval.surface --ref <commit>         # or from another commit
    python -m eval.surface --before-dir <tree>    # or from another checkout's tools/
    python -m eval.surface --backend oracle:OracleBackend --before-dir <tree>   # the self-test's plumbing

Counts tokens by difference, on the model in settings.yaml: the same one-message
call with what is counted and without it; the difference in `prompt_tokens`, which
includes cached tokens. For the starter's definitions, sent as the starter's
registry sends them (the SENT fields), and for ours (registry.schemas), it counts the
five together, each alone, and the planner's tool list (agent.plan._tool_list).
A definition counted alone includes the vendor's own tool-use preamble, which any
call carrying a tool pays once.

Then it prices a mean harness-arm run from its traces, at the model's uncached input
rate: each model_call line's `tools` names the definitions that call carried
(checks/FORMATS.md, section 11.10); a plan or revise call also carries the tool list
as text. submit_plan, the critique's verdict tool and any other tool outside the five
roles are the same before and after, and are left out. The same calls are priced with
the starter's counts, with ours, and as if every call had carried all five of ours.
Writes `surface` in reports/LAB_03.json (checks/FORMATS.md, section 11.8).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from agent.plan import _tool_list
from eval.count_writes import ARMS
from harness import LAB, ROOT
from harness.backends import make_backend
from harness.client import ModelClient, Usage
from harness.pricing import PriceSheet
from harness.roles import ROLES, role_of
from harness.settings import load_settings
from harness.trace import read_trace
from harness.tracker import Tracker
from tools import MODULES, SENT, RunContext, default_tools

STARTER_ROLES = dict(zip(MODULES, ROLES))   # the starter names each tool by its module
SYSTEM = "You are a connectivity test."
ASK = "Do not call any tool. Answer with the word ok."


def starter_schemas(ref: str | None, before_dir: Path | None) -> list[dict]:
    out = []
    for module in MODULES:
        if before_dir is not None:
            text = (before_dir / "tools" / f"{module}.json").read_text()
        else:
            text = subprocess.run(["git", "show", f"{ref}:tools/{module}.json"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout
        definition = json.loads(text)
        out.append({k: definition[k] for k in SENT if k in definition})
    return out


def prompt_tokens(client: ModelClient, tools: list[dict] | None = None, text: str = "") -> int:
    content = f"{text}\n\n{ASK}" if text else ASK
    response = client.create(system=SYSTEM, messages=[{"role": "user", "content": content}], tools=tools or None)
    return response.usage.prompt_tokens


def count(client: ModelClient, schemas: list[dict], role_of_name) -> dict:
    """The five together, each alone (by role), and the planner's text list."""
    bare = prompt_tokens(client)
    alone = {role_of_name(s["name"]): prompt_tokens(client, [s]) - bare for s in schemas}
    return {"block": prompt_tokens(client, schemas) - bare, "alone": alone,
            "list": prompt_tokens(client, text=f"The tools the plan may use:\n{_tool_list(schemas)}") - bare}


def harness_runs() -> list[list[dict]]:
    """Each finished harness-arm run's model_call lines: the evaluation issues only, since
    the development runs under FLAKY_WRITES carry the same switches."""
    evaluation = set(Tracker(ROOT, flaky=False, readback_fail=False).issue_numbers("eval"))
    out = []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_") or path.name.endswith(".calls.jsonl"):
            continue
        records = read_trace(path)
        if not records or records[0].get("type") != "run_start" or records[-1].get("type") != "run_end":
            continue
        start = records[0]
        if start.get("lab") != LAB or start.get("way") != "planned" or start.get("switches") != ARMS["harness"] \
                or start.get("issue") not in evaluation:
            continue
        if {r.get("terminal_reason") for r in records if r.get("type") == "end"} & {"quota", "rate_limited"}:
            continue
        out.append([r for r in records if r.get("type") == "model_call"])
    return out


def run_tokens(calls: list[dict], counts: dict) -> int:
    total = 0
    for call in calls:
        roles = [role_of(name) for name in call.get("tools") or []]
        total += sum(counts["alone"].get(r, 0) for r in roles if r)
        if call.get("purpose") in ("plan", "revise"):
            total += counts["list"]
    return total


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ref", default="lab-03-start", help="the git ref that holds the starter's definitions")
    p.add_argument("--before-dir", type=Path, help="a checkout whose tools/*.json are the starter's")
    p.add_argument("--backend", help="a scripted backend instead of settings.yaml's provider (tests the plumbing)")
    a = p.parse_args(argv)
    settings = load_settings(ROOT / "settings.yaml")
    prices = PriceSheet(ROOT / "pricing.yaml")
    client = ModelClient(make_backend(a.backend or settings.provider, settings), prices)
    ours = default_tools(RunContext(run_id="surface", tracker=None, repo_root=ROOT / "fixtures" / "repo")).schemas

    before = count(client, starter_schemas(a.ref, a.before_dir), STARTER_ROLES.get)
    after = count(client, ours, role_of)
    model = sorted(client.totals()["models"])[0]                        # the model that served the counts
    rate = prices.cost(model, Usage(input_tokens=1_000_000))            # USD per million, uncached
    runs = harness_runs()
    n = max(len(runs), 1)
    calls = sum(len(c) for c in runs) / n
    tokens_before = sum(run_tokens(c, before) for c in runs) / n
    tokens_after = sum(run_tokens(c, after) for c in runs) / n
    all_five = calls * after["block"]

    print(f"model {model}, input ${rate:.2f} per million, {len(runs)} harness-arm runs, "
          f"{calls:.2f} model calls a run")
    print(f"{'':28}{'starter':>10}{'ours':>10}")
    print(f"{'the five together':28}{before['block']:>10}{after['block']:>10}")
    for role in ROLES:
        print(f"{role + ', alone':28}{before['alone'].get(role, 0):>10}{after['alone'].get(role, 0):>10}")
    print(f"{'the planner tool list':28}{before['list']:>10}{after['list']:>10}")
    print(f"{'per run, as carried':28}{tokens_before:>10.0f}{tokens_after:>10.0f}")
    print(f"{'per run, all five each call':28}{'':>10}{all_five:>10.0f}")

    surface = {"tokens_before": before["block"], "tokens_after": after["block"],
               "list_tokens_before": before["list"], "list_tokens_after": after["list"],
               "calls_per_run": round(calls, 2),
               "cost_per_run_before": round(tokens_before * rate / 1e6, 6),
               "cost_per_run_after": round(tokens_after * rate / 1e6, 6),
               "cost_per_run_all_five": round(all_five * rate / 1e6, 6)}
    path = ROOT / "reports" / "LAB_03.json"
    report = json.loads(path.read_text())
    report["surface"] = surface
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(surface))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
