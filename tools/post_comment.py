"""issues_comment (post_comment.json): one public comment on an issue.

`idempotency_key` is never in the definition: the registry derives it and passes it,
and the tracker accepts each key once.
"""

import json

MAX_BODY = 2_000


def check(args: dict) -> list[str]:
    from tools import issue_problem
    problems = []
    problem = issue_problem(args.get("issue"))
    if problem:
        problems.append(problem)
    body = args.get("body")
    if isinstance(body, str):
        if not body.strip():
            problems.append("body: empty. Its first two lines are label: <bug | feature | question | docs> "
                            "and file: <path, or none>.")
        elif len(body) > MAX_BODY:
            problems.append(f"body: {len(body):,} characters, over the cap of {MAX_BODY:,}. Keep the two lines "
                            "and one or two sentences.")
    return problems


def describe(row: dict) -> str:
    """What the model is told about a comment, posted now or found already posted."""
    return json.dumps({"comment": f"comment-{row['id']}", "issue": f"issue-{row['issue']}"})


def run(ctx, issue, body, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError, issue_number

    try:
        row = ctx.tracker.post_comment(ctx.run_id, issue_number(issue), body, key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"issue: {issue} is not in the tracker. Comment on the issue you read; "
                        "this will not succeed with any other.")
    return describe(row)
