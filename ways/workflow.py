"""Way 2, the workflow: a fixed sequence decided in code."""

import json
import re

from harness.formats import format_triage_comment, parse_triage_comment
from ways.common import code_tool

MAX_TERMS = 3


def _terms(text: str) -> list[str]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        terms = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        terms = []
    if not terms:  # fall back to one term per line
        terms = [line.strip(" -*\"'`") for line in text.splitlines() if line.strip()]
    return [str(t) for t in terms if str(t).strip()][:MAX_TERMS]


NO_MATCHES = "No matches."


def gather(ctx) -> tuple[str, list[str], bool]:
    """Read the issue and run the searches. Returns the issue, the results, and
    whether any search found anything (Part D's hybrid hands off when none did)."""
    issue = code_tool(ctx, 0, "read_issue", {"number": ctx.issue_number})

    extract = ctx.client.create(system=ctx.prompt("extract_terms.md"),
                                messages=[{"role": "user", "content": issue}])
    ctx.trace.model_call(1, extract)

    found, any_hits = [], False
    for i, term in enumerate(_terms(extract.text), start=1):
        hits = code_tool(ctx, 1, "search_repo", {"query": term, "max_results": 10})
        any_hits = any_hits or hits.strip() != NO_MATCHES
        found.append(f"## search {i}: {term}\n{hits}")
    return issue, found, any_hits


def choose(ctx, issue: str, found: list[str]) -> tuple[str | None, str | None]:
    """One call to choose the label and the file from the search results."""
    response = ctx.client.create(
        system=ctx.prompt("choose.md"),
        messages=[{"role": "user", "content": f"The issue:\n\n{issue}\n\n---\n\nSearch results:\n\n" + "\n\n".join(found)}],
    )
    ctx.trace.model_call(2, response)
    return parse_triage_comment(response.text)


def post(ctx, label: str | None, file: str | None) -> None:
    code_tool(ctx, 2, "post_comment",
              {"number": ctx.issue_number, "body": format_triage_comment(label or "bug", file)})


def run(ctx) -> None:
    issue, found, _ = gather(ctx)
    post(ctx, *choose(ctx, issue, found))
