"""pulls_open (open_pr.json): one draft pull request on the mock remote.

`idempotency_key` is never in the definition: the registry passes it. Before every
attempt the registry also checks for an open PR from the same branch in this run.
"""

import json

MAX_TITLE, MAX_BODY = 120, 4_000


def check(args: dict) -> list[str]:
    from tools import issue_number, issue_problem
    problems = []
    problem = issue_problem(args.get("issue"))
    if problem:
        problems.append(problem)
    elif isinstance(args.get("branch"), str):
        want = f"repomind/issue-{issue_number(args['issue'])}"
        if args["branch"] != want:
            problems.append(f"branch: {args['branch']!r}; a pull request for {args['issue']} comes from {want}.")
    for name, cap in (("title", MAX_TITLE), ("body", MAX_BODY)):
        value = args.get(name)
        if isinstance(value, str) and not value.strip():
            problems.append(f"{name}: empty. " + ("One line saying what the change fixes." if name == "title"
                                                   else "Name the file first, then the change in prose."))
        elif isinstance(value, str) and len(value) > cap:
            problems.append(f"{name}: {len(value):,} characters, over the cap of {cap:,}. Shorten it.")
    return problems


def describe(row: dict) -> str:
    return json.dumps({"pull_request": f"pr-{row['id']}", "branch": row["branch"], "state": row["state"]})


def run(ctx, issue, branch, title, body, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError, issue_number

    try:
        row = ctx.tracker.open_pr(ctx.run_id, issue_number(issue), branch, title, body, key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"issue: {issue} is not in the tracker; this will not succeed with any other.")
    return describe(row)
