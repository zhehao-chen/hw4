"""Way 1, the direct call: one model call, no tools."""

from harness.formats import format_triage_comment, parse_triage_comment
from ways.common import code_tool


def run(ctx) -> None:
    issue = code_tool(ctx, 0, "read_issue", {"number": ctx.issue_number})
    response = ctx.client.create(
        system=ctx.prompt("direct.md"),
        messages=[{"role": "user", "content": f"{ctx.repo_summary}\n\n---\n\nThe issue:\n\n{issue}"}],
    )
    ctx.trace.model_call(1, response)
    label, file = parse_triage_comment(response.text)
    code_tool(ctx, 1, "post_comment",
              {"number": ctx.issue_number, "body": format_triage_comment(label or "bug", file)})
