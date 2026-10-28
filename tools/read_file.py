"""code_read_file (read_file.json): one file of the private codebase, by its exact path.

A path is compared with the repository's own file list, case included, never with
the file system: on a case-insensitive disk (macOS's default) src/report.ts would
otherwise open src/Report.ts and report success. A path not in the list is an
error that names the closest paths that are: the same path in another case, and
any path at least NEAR alike, case ignored.
"""

from __future__ import annotations

import difflib
from pathlib import Path

CAPS = {"concise": 8_000, "detailed": 20_000}
NEAR = 0.9          # how alike, from 0 to 1, a path must be to be offered as a near miss
MAX_SUGGESTIONS = 5


def repo_files(repo_root: Path) -> list[str]:
    from tools.search_repo import EXCLUDED_DIRS
    root = Path(repo_root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and not (set(p.relative_to(root).parts) & EXCLUDED_DIRS))


def near_misses(path: str, files: list[str]) -> list[str]:
    low = path.lower()
    scored = [(difflib.SequenceMatcher(None, low, f.lower()).ratio(), f) for f in files if f != path]
    return [f for score, f in sorted(scored, key=lambda x: (-x[0], x[1])) if score >= NEAR][:MAX_SUGGESTIONS]


def check(args: dict) -> list[str]:
    path = args.get("path")
    if isinstance(path, str) and not path.strip():
        return ["path: empty. Give a file's path relative to the repository root, exactly as code_search "
                "printed it, such as src/util/money.ts."]
    return []


def run(ctx, path, response_format):
    from harness.formats import normalize_path
    from tools import ToolError

    rel = normalize_path(path)
    files = repo_files(ctx.repo_root)
    if rel not in files:
        close = near_misses(rel or "", files)
        hint = (f" Did you mean {', '.join(close)}? Paths match exactly, case and extension included."
                if close else " Copy a path exactly as code_search printed it, or search first.")
        raise ToolError(f"path: no such file: {path}.{hint}")
    text = (Path(ctx.repo_root) / rel).read_text()
    cap = CAPS[response_format]
    head = f"{rel} ({len(text):,} characters)\n"
    if len(text) > cap:
        return head + text[:cap] + f"\n[cut at {cap:,} of {len(text):,} characters; detailed reads up to 20,000]"
    return head + text
