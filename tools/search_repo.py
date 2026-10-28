"""code_search (search_repo.json): literal, case-insensitive search over the private codebase.

It reads the prebuilt index, fixtures/search_index/index.json, and returns JSON:
{query, query_valid, count, truncated, index_age, results: [{path, line, excerpt}]}.
A search that matches nothing is a success with count 0 and query_valid true. A
malformed one is an error, refused at the boundary by check() and again here:

  1. a query that is empty or only whitespace;
  2. a query longer than MAX_QUERY_CHARS;
  3. a path_glob that is not a valid glob (glob_problem).
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {"config", "node_modules", ".git"}
MAX_QUERY_CHARS = 200
INDEX = "fixtures/search_index/index.json"
GLOB_CHARS = re.compile(r"^[A-Za-z0-9_.\-/*?\[\]{},]+$")
CAPS = {"concise": (10, 120), "detailed": (20, 300)}   # results, excerpt characters

RESULT_SCHEMA = {
    "type": "object",
    "required": ["query", "query_valid", "count", "truncated", "index_age", "results"],
    "properties": {
        "query": {"type": "string"}, "query_valid": {"type": "boolean"}, "count": {"type": "integer"},
        "truncated": {"type": "boolean"}, "index_age": {"type": "string"},
        "results": {"type": "array", "items": {"type": "object", "required": ["path", "line", "excerpt"]}},
    },
}


def glob_problem(pattern: str) -> str | None:
    """Why `pattern` is not a valid path glob, or None when it is one."""
    if pattern.startswith("/"):
        return "a glob is relative to the repository root; it cannot start with /"
    if ".." in pattern.split("/"):
        return "a glob cannot leave the repository (..)"
    if not GLOB_CHARS.match(pattern):
        return "a glob uses letters, digits, / . _ - and the wildcards * ? [ ] { }; no spaces, colons or quotes"
    depth = 0
    for ch in pattern:
        depth += {"[": 1, "]": -1}.get(ch, 0)
        if depth not in (0, 1):
            return "a glob's [ and ] must pair up"
    if depth:
        return "a glob's [ and ] must pair up"
    if pattern.count("{") != pattern.count("}"):
        return "a glob's { and } must pair up"
    return None


def check(args: dict) -> list[str]:
    """Content rules the schema cannot hold, each with the fix."""
    problems = []
    query = args.get("query")
    if isinstance(query, str):
        if not query.strip():
            problems.append("query: empty. Give a literal term to find, such as an identifier from the issue "
                            "(minorDigits) or a quoted error message.")
        elif len(query) > MAX_QUERY_CHARS:
            problems.append(f"query: {len(query)} characters, over the cap of {MAX_QUERY_CHARS}. Search for the "
                            "most distinctive few words, or one identifier.")
    glob = args.get("path_glob")
    if isinstance(glob, str):
        why = glob_problem(glob) if glob else "it is empty"
        if why:
            problems.append(f"path_glob: {glob!r} is not a glob: {why}. For example src/util/** or "
                            "src/**/*.ts, or null to search everything.")
    return problems


def _expand(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    return [p for option in match.group(1).split(",")
            for p in _expand(pattern[:match.start()] + option + pattern[match.end():])]


def _matches(path: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path, p.replace("**/", ""))
               for p in _expand(pattern))


def load_index(root: Path) -> dict:
    return json.loads((Path(root) / INDEX).read_text())


def age(built_at: str, now: float | None = None) -> str:
    built = datetime.strptime(built_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    days = int(((now or time.time()) - built.timestamp()) // 86400)
    return "today" if days < 1 else f"{days} day{'s' if days != 1 else ''} ago"


def run(ctx, query, path_glob, response_format):
    from tools import ToolError

    problems = check({"query": query, "path_glob": path_glob})
    if problems:
        raise ToolError(" ".join(problems))
    index = load_index(Path(ctx.repo_root).parent.parent)
    needle = query.strip().lower()
    hits = [(rel, number, line.strip())
            for rel, lines in sorted(index["files"].items()) if _matches(rel, path_glob)
            for number, line in enumerate(lines, 1) if needle in line.lower()]
    limit, width = CAPS[response_format]
    return json.dumps({
        "query": query, "query_valid": True, "count": len(hits), "truncated": len(hits) > limit,
        "index_age": age(index["built_at"]),
        "results": [{"path": rel, "line": number, "excerpt": text[:width]} for rel, number, text in hits[:limit]],
    })
