"""Way 3, the agent: the model decides what to call and when to stop."""

from agent.loop import load_bounds, run_loop


def run(ctx) -> None:
    run_loop(ctx.client, ctx.tools, ctx.prompt("agent.md"),
             f"Triage issue #{ctx.issue_number}.", load_bounds(), ctx.trace)
