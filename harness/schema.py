"""Check a JSON value against a JSON schema: the part of JSON Schema strict mode uses.

    from harness.schema import errors
    problems = errors(instance, schema)     # [] when the instance fits

A vendor may accept "strict": true and still not enforce it: one returned plans
missing a required field. So check what your planner returns against
agent/plan_schema.json yourself, before the four checks (checks/FORMATS.md,
section 10.2). It reads: type (one, or a list such as ["string", "null"]),
required, properties, additionalProperties, items, enum, const, anyOf, oneOf, and
local references ("#/$defs/step"). Anything else in a schema is ignored. Each
problem is one line, naming where it is: "steps[2].tool: required, and missing".
"""

from __future__ import annotations

_TYPES = {
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def errors(instance, schema: dict) -> list[str]:
    """Every way `instance` breaks `schema`, one line each; [] when it fits."""
    out: list[str] = []
    _check(instance, schema, schema, "", out)
    return out


def _resolve(schema, root):
    for _ in range(20):
        if not (isinstance(schema, dict) and "$ref" in schema):
            break
        node = root
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema = node
    return schema if isinstance(schema, dict) else {}


def _kind(value) -> str:
    return next((name for name in ("null", "boolean", "integer", "number", "string", "array", "object")
                 if _TYPES[name](value)), type(value).__name__)


def _check(value, schema, root, path: str, out: list[str]) -> None:
    schema = _resolve(schema, root)
    where = path or "the top level"
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if branches:
            results = [errors_at(value, b, root, path) for b in branches]
            fits = sum(1 for r in results if not r)
            if fits == 0:
                closest = min(results, key=len)
                out.append(f"{where}: fits none of its {len(branches)} shapes ({closest[0]})")
            elif key == "oneOf" and fits > 1:
                out.append(f"{where}: fits {fits} of its oneOf shapes, and must fit exactly one")
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_TYPES.get(k, lambda v: True)(value) for k in kinds):
            out.append(f"{where}: {_kind(value)}, where the schema wants {' or '.join(kinds)}")
            return
    if "const" in schema and value != schema["const"]:
        out.append(f"{where}: {value!r}, where the schema wants {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                out.append(f"{_join(path, name)}: required, and missing")
        extra = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name in props:
                _check(item, props[name], root, _join(path, name), out)
            elif extra is False:
                out.append(f"{_join(path, name)}: not in the schema, which allows no other properties")
            elif isinstance(extra, dict):
                _check(item, extra, root, _join(path, name), out)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            _check(item, schema["items"], root, f"{path}[{i}]", out)


def errors_at(value, schema, root, path: str) -> list[str]:
    out: list[str] = []
    _check(value, schema, root, path, out)
    return out


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name
