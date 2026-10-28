"""The ways of doing the triage task: Assignment 1's four (direct, workflow, agent and
hybrid), and Assignment 2's planned and notes. Each module has run(ctx) -> None.

ctx is a harness.runner.WayContext: ctx.issue_number, ctx.client, ctx.tools,
ctx.trace, ctx.call_tool(step, name, input), ctx.prompt(name), ctx.repo_summary. A way succeeds only if, when it
returns, the tracker holds exactly one comment from this run on this issue,
with the lines `label: <label>` and `file: <path or none>`.
"""
