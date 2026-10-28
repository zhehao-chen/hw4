"""Assignment 1, Part B: the grounded check."""

from harness.formats import normalize_path, parse_triage_comment


def check(tracker, run_id: str, issue_number: int, answer: dict) -> bool:
    comments = tracker.comments(run_id=run_id, issue=issue_number)
    if len(comments) != 1:  # none means nothing happened; two means the run cannot say which it meant
        return False
    label, file = parse_triage_comment(comments[0]["body"])
    return label == answer["label"] and file == normalize_path(answer["file"])
