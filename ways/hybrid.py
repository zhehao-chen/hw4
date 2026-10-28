"""Way 4, Part D's hybrid: the workflow, and the agent where the workflow is
likely wrong.

The hand-off rule, chosen from the Part B traces: the workflow was wrong when the
file it chose appeared in none of its search results (it guessed), and that test
also covers searches that found nothing. A question, whose answer is `none`,
stays with the workflow. The rule uses only what the workflow can see at runtime,
never the known answers. Its cost: on a hand-off the choice call is spent before
the agent starts afresh.
"""

from ways import agent, workflow


def run(ctx) -> None:
    issue, found, _ = workflow.gather(ctx)
    label, file = workflow.choose(ctx, issue, found)
    grounded = bool(file) and file != "none" and file in "\n".join(found)
    if grounded or (label == "question" and file in (None, "none")):
        workflow.post(ctx, label, file)
    else:  # the choice is a guess: hand the issue to the agent, which starts afresh
        agent.run(ctx)
