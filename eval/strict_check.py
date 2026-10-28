"""Assignment 2's working solution, Part A, task 5: record strict_compiles.

    python -m eval.strict_check                                  # the provider in settings.yaml
    python -m eval.strict_check --backend harness.scripted:ScriptedTriage   # scripted: null

Sends one planner request, its plan tool marked "strict": true (agent/plan.py),
through the backend, and writes reports/LAB_02.json's schema.strict_compiles:

    true   the request was accepted. Accepted, not enforced: a vendor may accept
           "strict" and still return a plan that breaks the schema, which is why
           ways/planned.py checks every plan with harness.schema.errors;
    false  the request was refused for its schema (a 400, or an error naming the schema);
    null   the backend is scripted (harness.scripted), so there is no
           vendor and no strict mode to test.

The request costs a few hundred tokens, outside runs/ and the ledger.
"""

from __future__ import annotations

import argparse
import json

from agent.plan import make_plan
from harness import ROOT
from harness.backends import REAL_BACKENDS, make_backend
from harness.client import ModelClient
from harness.pricing import PriceSheet
from harness.settings import load_settings
from harness.tracker import Tracker
from tools import RunContext, default_tools


def strict_compiles(backend_name: str | None) -> tuple[bool | None, str]:
    settings = load_settings(ROOT / "settings.yaml")
    backend_name = backend_name or settings.provider
    if backend_name not in REAL_BACKENDS:
        return None, f"{backend_name or 'no backend'} has no vendor behind it, so no strict mode to test"
    client = ModelClient(make_backend(backend_name, settings), PriceSheet(ROOT / "pricing.yaml"))
    schemas = default_tools(RunContext("strict-check", Tracker(ROOT), ROOT / "fixtures" / "repo")).schemas
    try:
        make_plan(client, 4191, schemas)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status == 400 or "schema" in str(exc).lower():
            return False, f"refused: {str(exc)[:300]}"
        raise
    return True, f"accepted by {settings.model} through {backend_name}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--backend", help="default: the provider in settings.yaml")
    value, why = strict_compiles(p.parse_args().backend)
    path = ROOT / "reports" / "LAB_02.json"
    report = json.loads(path.read_text()) if path.exists() else {}
    report.setdefault("schema", {})["strict_compiles"] = value
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"strict_compiles: {json.dumps(value)} ({why})")


if __name__ == "__main__":
    main()
