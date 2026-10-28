"""The course's schema audit for Assignment 3, Part A. Course file: do not edit it.

    python tools/audit_schemas.py            # checks tools/*.json against tools/audit_limits.yaml

It reads your five definitions and tools/roles.yaml, never calls a model, and
checks what Part A asks of every definition:

  names       namespaced, one scheme for all five: a shared prefix (issues_read,
              issues_comment) or a shared suffix (read_issues, comment_issues) naming
              the service; the issue tracker's two tools share one, the codebase's two
              another, the pull requests' tool a third
  closed      additionalProperties: false on every object
  limits      both vendors' strict-mode limits at once (audit_limits.yaml): no optional
              parameters, at most 16 nullable or union-typed ones across the five, at
              most 5 levels of nesting and 100 properties, no validation keywords
  strict      a "strict" field, true or false, on every definition
  examples    two examples per tool, each a valid call ({"input": {...}}), in the
              definition file; the registry renders them into the description
  result      every description says what an empty result means (a sentence with
              "empty", "no match", "nothing" or "zero") and what caps a response ("at
              most", "cap", "truncat" or "limit")
  format      the search and read_file tools take a response_format of concise or detailed
  roles       tools/roles.yaml names five tools that exist, and arguments they have

It prints the three counts Part A's report asks for, and exits 1 if anything fails.
checks/check_03.py runs the same audit.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from harness.roles import ROLE_ARGS, ROLES, roles  # noqa: E402
from harness.schema import errors  # noqa: E402

MODULES = ("read_issue", "search_repo", "read_file", "post_comment", "open_pr")
SERVICE = {"read_issue": "tracker", "comment": "tracker", "search": "code", "read_file": "code", "open_pr": "pulls"}
EMPTY = re.compile(r"empty|no match|nothing|zero", re.IGNORECASE)
CAP = re.compile(r"at most|\bcap|truncat|limit", re.IGNORECASE)
NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def load_limits(root: Path = ROOT) -> dict:
    return yaml.safe_load((root / "tools" / "audit_limits.yaml").read_text())


def load_definitions(root: Path = ROOT) -> dict[str, dict]:
    """{module: definition}, for the five modules."""
    return {m: json.loads((root / "tools" / f"{m}.json").read_text()) for m in MODULES}


def _types(node: dict) -> list:
    kinds = node.get("type")
    return kinds if isinstance(kinds, list) else ([kinds] if kinds else [])


def _walk(node, path: str, level: int, out: dict, limits: dict) -> None:
    """Every object, property and keyword under one schema node."""
    if not isinstance(node, dict):
        return
    for keyword in limits["validation_keywords"]:
        if keyword in node:
            out["keywords"].append(f"{path or 'the top level'}: {keyword}")
    is_object = "object" in _types(node) or "properties" in node
    if is_object:
        out["depth"] = max(out["depth"], level)
        if node.get("additionalProperties") is not False:
            out["open"].append(path or "the top level")
        props = node.get("properties") or {}
        required = set(node.get("required") or [])
        for name, prop in props.items():
            out["properties"] += 1
            where = f"{path}.{name}" if path else name
            if name not in required:
                out["optional"].append(where)
            if isinstance(prop, dict) and (len(_types(prop)) > 1 or "anyOf" in prop or "oneOf" in prop):
                out["unions"].append(where)
            _walk(prop, where, level + 1, out, limits)
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            _walk(node[key], f"{path}[]" if key == "items" else path, level, out, limits)
    for key in ("anyOf", "oneOf"):
        for branch in node.get(key) or []:
            _walk(branch, path, level, out, limits)


def _scheme(names: dict[str, str], services: int) -> str | None:
    """'prefix' or 'suffix' if one scheme namespaces all five by service, else None."""
    for scheme, pick in (("prefix", lambda n: n.split("_")[0]), ("suffix", lambda n: n.split("_")[-1])):
        token = {role: pick(name) for role, name in names.items()}
        by_service: dict[str, set] = {}
        for role, t in token.items():
            by_service.setdefault(SERVICE[role], set()).add(t)
        if all(len(t) == 1 for t in by_service.values()) and len({next(iter(t)) for t in by_service.values()}) == services:
            return scheme
    return None


def audit(root: Path = ROOT) -> dict:
    """{"passed": bool, "problems": {check: [lines]}, "counts": {...}, "scheme": str|None}."""
    limits = load_limits(root)
    problems: dict[str, list[str]] = {k: [] for k in
                                      ("roles", "names", "closed", "limits", "strict", "examples", "result", "format")}
    try:
        defs = load_definitions(root)
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "problems": {"roles": [f"a definition could not be read: {exc}"]},
                "counts": {}, "scheme": None}
    by_name = {d.get("name"): (m, d) for m, d in defs.items()}
    try:
        table = roles(root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        table = {}
        problems["roles"].append(str(exc))
    names = {}
    for role in ROLES:
        entry = table.get(role)
        if not entry:
            continue
        if entry["tool"] not in by_name:
            problems["roles"].append(f"roles.yaml: {role} names {entry['tool']!r}, which no definition is called")
            continue
        names[role] = entry["tool"]
        props = (by_name[entry["tool"]][1].get("input_schema") or {}).get("properties") or {}
        for role_arg in ROLE_ARGS[role]:
            if entry["args"].get(role_arg) not in props:
                problems["roles"].append(f"roles.yaml: {role}'s {role_arg} is {entry['args'].get(role_arg)!r}, "
                                         f"which {entry['tool']} has no argument called")

    counts = {"tools": len(defs), "strict_tools": 0, "optional_params": 0, "union_types": 0}
    for module, d in defs.items():
        name = d.get("name", module)
        if not NAME.match(str(name)):
            problems["names"].append(f"{name}: a name is lowercase words joined by _, at least two of them")
        schema = d.get("input_schema") or {}
        walked = {"keywords": [], "open": [], "optional": [], "unions": [], "depth": 0, "properties": 0}
        _walk(schema, "", 1, walked, limits)
        for where in walked["open"]:
            problems["closed"].append(f"{name}: {where} lacks additionalProperties: false")
        for where in walked["keywords"]:
            problems["limits"].append(f"{name}: {where} is a validation keyword; check it at the boundary instead")
        if walked["depth"] > limits["depth"]:
            problems["limits"].append(f"{name}: {walked['depth']} levels of nesting; the limit is {limits['depth']}")
        if walked["properties"] > limits["properties"]:
            problems["limits"].append(f"{name}: {walked['properties']} properties; the limit is {limits['properties']}")
        counts["optional_params"] += len(walked["optional"])
        counts["union_types"] += len(walked["unions"])
        for where in walked["optional"]:
            problems["limits"].append(f"{name}: {where} is optional; make it required, and nullable if it may be absent")
        if not isinstance(d.get("strict"), bool):
            problems["strict"].append(f"{name}: no \"strict\": true or false")
        elif d["strict"]:
            counts["strict_tools"] += 1
        examples = d.get("examples")
        if not isinstance(examples, list) or len(examples) < limits["examples_per_tool"]:
            problems["examples"].append(f"{name}: {len(examples) if isinstance(examples, list) else 0} examples; "
                                        f"want {limits['examples_per_tool']}, a typical call first")
        else:
            for i, example in enumerate(examples):
                given = example.get("input") if isinstance(example, dict) else None
                broken = errors(given, schema) if isinstance(given, dict) else ["no \"input\" object"]
                if broken:
                    problems["examples"].append(f"{name}: example {i + 1} is not a valid call: {broken[0]}")
        description = str(d.get("description") or "")
        if not EMPTY.search(description):
            problems["result"].append(f"{name}: the description never says what an empty result means")
        if not CAP.search(description):
            problems["result"].append(f"{name}: the description never says what caps a response")
    for role in ("search", "read_file"):
        if role not in names:
            continue
        props = (by_name[names[role]][1].get("input_schema") or {}).get("properties") or {}
        if not any(set(limits["response_format"]) <= set((p or {}).get("enum") or []) for p in props.values()):
            problems["format"].append(f"{names[role]}: no response_format argument with "
                                      f"{' and '.join(limits['response_format'])}")
    if counts["union_types"] > limits["union_params"]:
        problems["limits"].append(f"{counts['union_types']} nullable or union-typed parameters across the five; "
                                  f"the limit is {limits['union_params']}")
    if counts["strict_tools"] > limits["strict_tools"]:
        problems["limits"].append(f"{counts['strict_tools']} strict tools; the limit is {limits['strict_tools']}")
    scheme = _scheme(names, limits["services"]) if len(names) == len(ROLES) else None
    if len(names) == len(ROLES) and scheme is None:
        problems["names"].append("the five names do not share one namespacing scheme: a prefix or a suffix "
                                 "naming the service, one for the issue tracker's two tools, one for the "
                                 "codebase's two, one for the pull requests")
    return {"passed": not any(problems.values()), "problems": problems, "counts": counts, "scheme": scheme}


def main() -> int:
    result = audit()
    c = result["counts"]
    print(f"strict tools {c.get('strict_tools')}, optional parameters {c.get('optional_params')}, "
          f"nullable or union-typed parameters {c.get('union_types')}"
          + (f"; names namespaced by {result['scheme']}" if result["scheme"] else ""))
    for check, lines in result["problems"].items():
        for line in lines:
            print(f"  {check:<9} {line}")
    print("audit passed" if result["passed"] else "audit failed")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
