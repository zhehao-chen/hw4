"""Assignment 2's working solution, Part D: the second pass's two critics.

verify is code: it knows the repository and this run's own record, and nothing
else. self_critique is the same model with nothing new (Lecture 2, slide 35).
"""

from __future__ import annotations

from pathlib import Path

from harness.formats import LABELS, normalize_path, parse_triage_comment
from harness.trace import read_trace

ROOT = Path(__file__).resolve().parent.parent
VERDICT = {
    "name": "verdict",
    "description": "Accept the draft as it is, or ask for a revision and say why.",
    "input_schema": {"type": "object", "additionalProperties": False, "required": ["decision", "reason"],
                     "properties": {"decision": {"type": "string", "enum": ["accept", "revise"]},
                                    "reason": {"type": ["string", "null"]}}},
}


def seen_paths(trace_path) -> list[str]:
    """Every file this run's tool calls returned so far, search results and reads, in order."""
    found = [p for r in read_trace(trace_path) if r.get("type") == "tool_call" for p in r.get("paths") or []]
    return list(dict.fromkeys(found))


def verify(draft: str, ctx) -> dict:
    label, file = parse_triage_comment(draft)
    if label not in LABELS or file is None:                                   # 1: it parses
        return {"passed": False, "reasons": ["the comment does not parse: it needs a 'label:' line with one of "
                                             f"{', '.join(LABELS)} and a 'file:' line with a path or none"]}
    reasons = []
    if file != "none":
        repo = (Path(ctx.root) / "fixtures" / "repo").resolve()
        target = (repo / file).resolve()
        if repo not in target.parents or not target.is_file():                # 2: the path exists
            reasons.append(f"{file} does not exist in the repository")
        elif normalize_path(file) not in seen_paths(ctx.trace.path):          # 3: this run saw it
            reasons.append(f"this run never saw {file}: no search result or read returned it")
        if label == "question":                                               # 4: the label and the file agree
            reasons.append(f"the label and the file disagree: a question names none, not {file}")
    elif label != "question":
        reasons.append(f"the label and the file disagree: a {label} names a file, not none")
    return {"passed": not reasons, "reasons": reasons}


def self_critique(client, draft: str, evidence: dict, trace=None, *, step: int = 0) -> dict:
    user = (f"The draft comment:\n\n{draft}\n\n---\n\nThe issue:\n\n{evidence.get('issue', '')}\n\n---\n\n"
            "What the run's steps returned:\n\n" + "\n\n".join(evidence.get("results", [])))
    response = client.create(system=(ROOT / "prompts" / "self_critique.md").read_text(),
                             messages=[{"role": "user", "content": user}], tools=[VERDICT])
    if trace is not None:
        trace.model_call(step, response, purpose="critique")
    for call in response.tool_calls:
        if call.name == VERDICT["name"] and call.input.get("decision") in ("accept", "revise"):
            return {"decision": call.input["decision"], "reason": call.input.get("reason")}
    return {"decision": "accept", "reason": None}   # no verdict: the critic has nothing to add
