"""Assignment 2's working solution, Part G: the planned way with the second pass off,
a progress file and a compaction.

The executor carries its context as turns, one per step. Past COMPACT_AT tokens
(estimated as characters over four), every turn but the last KEEP becomes one
model-written summary. The progress file is written after every step, and with
--notes on its text goes into every later call; with --notes off it is written and
never shown; it holds step ids and paths, never search terms, which come from the
issue, and says what it records, so that a model does not read its paths as a
to-do list. Every executor call sees the run's history so far, its step results
oldest first, as compacted. At the end of the run, however it ended (comment
posted, escalated, halted), one call asks six questions, "Has this run seen
<path>?": the three earliest paths the run's tool calls returned (fewer if it saw
fewer), and paths it never saw for the rest. A run that never passed COMPACT_AT is
compacted once first, so that every run asks after a compaction.
"""

from __future__ import annotations

import json
import math
import re

from agent.critique import seen_paths
from ways.planned import CONTEXT_CHARS, Executor, plan_until_valid

COMPACT_AT = 300      # tokens: low enough that every triage run compacts before its questions (a test setting)
KEEP = 1              # turns kept as they were
QUESTIONS, SEEN_QUESTIONS = 6, 3   # every seen path up to three, then unseen ones to make six
SUMMARY = "## Summary of the earlier steps"


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


ABOUT = ("What this run has done so far: the ids of the plan steps it has run, and every file a search "
         "returned or it read, in the order it saw them. A record of the past, not a to-do list.")


def run(ctx) -> None:
    plan = plan_until_valid(ctx)
    executor = NotesExecutor(ctx, plan or {"meta": {}, "steps": []})
    if plan is not None:
        ctx.trace.plan(1, plan)
        executor.run()
    executor.ask()        # at the end of every run, however it ended


class NotesExecutor(Executor):
    critique = False

    def __init__(self, ctx, plan):
        super().__init__(ctx, plan)
        self.turns: list[str] = []
        self.paths: list[str] = []
        self.compactions = 0

    # -- the progress file, after every step -------------------------------------------
    def record(self, step, args, result, error=None):
        entry = super().record(step, args, result, error)
        self.turns.append(f"## Step {entry['id']}, {entry['tool']}, {entry['status']}\n"
                          f"{self.outputs.get(str(entry['id']), '')[:CONTEXT_CHARS]}")
        for path in seen_paths(self.ctx.trace.path):
            if path not in self.paths:
                self.paths.append(path)
        self.ctx.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.progress_path.write_text(json.dumps({
            "about": ABOUT,
            "steps_done": [r["id"] for r in self.results],
            "paths": self.paths,
            "plan_version": self.version,
        }, indent=1) + "\n")
        return entry

    def notes(self) -> str:
        if self.ctx.notes != "on" or not self.ctx.progress_path.exists():
            return ""
        return "Your progress file, kept outside this conversation:\n" + self.ctx.progress_path.read_text()

    # -- the context, compacted past the threshold -------------------------------------------
    def compact(self, force: bool = False) -> None:
        size = tokens("\n\n".join(self.turns))
        older, recent = self.turns[:-KEEP], self.turns[-KEEP:]
        if force and not older:
            older, recent = self.turns, []        # a forced compaction of a one-turn history
        if not older or (len(older) == 1 and older[0].startswith(SUMMARY)) or (size <= COMPACT_AT and not force):
            return                                # nothing new to summarize, or under the threshold
        self.calls += 1
        response = self.ctx.client.create(system=self.ctx.prompt("compact.md"),
                                          messages=[{"role": "user", "content": "\n\n".join(older)}])
        self.ctx.trace.model_call(self.calls, response)
        self.turns = [f"{SUMMARY}\n{response.text}"] + recent
        self.compactions += 1
        self.ctx.trace.event("compaction", threshold=COMPACT_AT, tokens=size, summarized=len(older), kept=len(recent),
                             forced=force)

    def context(self) -> list[str]:
        self.compact()
        notes = self.notes()
        return self.turns + ([notes] if notes else [])

    # -- the questions, at the end of the run, after a compaction ----------------------------------
    def ask(self) -> None:
        self.compact(force=self.compactions == 0)
        seen = seen_paths(self.ctx.trace.path)
        repo = self.ctx.root / "fixtures" / "repo"
        unseen = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*")
                        if p.is_file() and "config" not in p.relative_to(repo).parts
                        and p.relative_to(repo).as_posix() not in seen)
        asked_seen = seen[:SEEN_QUESTIONS]
        start = self.ctx.issue_number % max(1, len(unseen) - QUESTIONS)
        paths = asked_seen + unseen[start:start + QUESTIONS - len(asked_seen)]
        questions = "\n".join(f"{i}. Has this run seen `{path}`: did a search return it, or did you read it?"
                               for i, path in enumerate(paths, 1))
        self.calls += 1
        response = self.ctx.client.create(
            system=self.ctx.prompt("question.md"),
            messages=[{"role": "user", "content": "\n\n".join(self.context() + [questions])}])
        self.ctx.trace.model_call(self.calls, response)
        for i, path in enumerate(paths, 1):
            said = re.search(rf"^\W*{i}\W+(yes|no)\b", response.text, re.IGNORECASE | re.MULTILINE)
            self.ctx.trace.event("question", path=path, answer=said.group(1).lower() if said else "no")
