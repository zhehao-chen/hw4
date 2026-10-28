"""issues_read (read_issue.json): one issue from the tracker, and its discussion.
Untrusted content: anyone can file an issue, and anyone can comment on one.

From Assignment 4 the result carries the issue's discussion: the comments people
wrote on it, as the fixture holds them. It never carries a comment a run wrote."""

MAX_BODY = 6_000
MAX_DISCUSSION = 4_000


def check(args: dict) -> list[str]:
    """Content rules the schema cannot hold, checked before the tool runs."""
    from tools import issue_problem
    problem = issue_problem(args.get("issue"))
    return [problem] if problem else []


def run(ctx, issue):
    from harness.tracker import IssueNotFound
    from tools import ToolError, issue_number

    n = issue_number(issue)
    try:
        found = ctx.tracker.issue(n)
    except IssueNotFound:
        raise ToolError(f"issue: {issue} is not in the tracker. Pass the issue you were asked to triage, "
                        "as issue-<number>; this will not succeed with any other number.")
    body = found["body"]
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + f"\n[body cut at {MAX_BODY:,} of {len(found['body']):,} characters]"
    history = "".join(f"; {word} on {found[word]}" for word in ("closed", "reopened") if found.get(word))
    text = (f"issue-{found['number']}: {found['title']}\n"
            f"Opened by {found['author']} on {found['opened']}{history}\n\n{body}")
    discussion = found.get("discussion") or []
    if not discussion:
        return text + "\n\nDiscussion: none."
    lines = [f"--- {c['author']}" + (f" ({c['role']})" if c.get("role") else "") + f", {c['date']}\n{c['body']}"
             for c in discussion]
    thread = "\n\n".join(lines)
    if len(thread) > MAX_DISCUSSION:
        thread = thread[:MAX_DISCUSSION] + f"\n[discussion cut at {MAX_DISCUSSION:,} characters]"
    return text + f"\n\nDiscussion ({len(discussion)} comments, written by people):\n\n{thread}"
