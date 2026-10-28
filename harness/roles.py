"""Which of your tools plays each of RepoMind's five roles: tools/roles.yaml.

Assignment 3 lets you rename every tool and every argument. The checker, the
scripted models and the trace still need to find the search tool, the comment
tool and the rest, and to know which argument is the query or the path. They read
tools/roles.yaml, which you keep up to date as you rename (checks/FORMATS.md,
section 11.2):

    search: {tool: <your search tool's name>, args: {query: <its query argument>, path: <its path filter>}}

    from harness.roles import tool_for, role_of, arg
    tool_for("search")            # "search_repo" in the starter
    role_of("search_repo")        # "search"
    arg("search", "query")        # "query" in the starter
"""

from __future__ import annotations

from pathlib import Path

import yaml

from harness import ROOT

ROLES = ("read_issue", "search", "read_file", "comment", "open_pr")
ROLE_ARGS = {"read_issue": ("number",), "search": ("query", "path"), "read_file": ("path",),
             "comment": ("number", "body"), "open_pr": ("number", "branch", "title", "body")}
WRITES = ("comment", "open_pr")


def roles(root: Path | None = None) -> dict[str, dict]:
    """{role: {"tool": name, "args": {role_arg: your_arg}}}, for all five roles."""
    path = Path(root or ROOT) / "tools" / "roles.yaml"
    data = yaml.safe_load(path.read_text()) or {}
    out = {}
    for role in ROLES:
        entry = data.get(role) or {}
        if not isinstance(entry, dict) or not entry.get("tool"):
            raise ValueError(f"tools/roles.yaml: role {role!r} needs a tool (checks/FORMATS.md, section 11.2)")
        args = entry.get("args") or {}
        missing = [a for a in ROLE_ARGS[role] if not args.get(a)]
        if missing:
            raise ValueError(f"tools/roles.yaml: role {role!r} needs args {missing}")
        out[role] = {"tool": str(entry["tool"]), "args": {k: str(v) for k, v in args.items()}}
    return out


def tool_for(role: str, root: Path | None = None) -> str:
    return roles(root)[role]["tool"]


def role_of(name: str, root: Path | None = None) -> str | None:
    """The role a tool name plays, or None for a name no role uses."""
    try:
        table = roles(root)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return next((role for role, entry in table.items() if entry["tool"] == name), None)


def arg(role: str, role_arg: str, root: Path | None = None) -> str:
    return roles(root)[role]["args"][role_arg]
