"""Assignment 4, Part A: the checkpointer. This file is yours.

A checkpointer saves one run's state, so its checkpoints are keyed by the run's
run_id (frameworks call one run's line of checkpoints a thread). Save them on a
durable backend: a SQLite file such as state/checkpoints.db is fine; an in-memory
store is not, because it dies with the process. A sync save is on disk before
save() returns.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.4), so keep them:

    Checkpointer(path=None)                    # None: your default file
    .save(run_id, checkpoint, *, step, mode)   # one checkpoint; mode is sync, async or exit
    .last(run_id) -> dict | None               # the run's latest checkpoint, or None
    .all(run_id) -> list[dict]                 # every checkpoint the run saved, oldest first
    .runs() -> list[str]                       # every run_id that has a checkpoint

A checkpoint is a dict of exactly the five fields in harness.formats.CHECKPOINT_FIELDS:
plan, step_status, completed_calls (each with its idempotency key), findings and
current_step. Everything in it must serialize, and the conversation is not in it.
Every save is also a trace line, trace.event("checkpoint", step=..., mode=...),
which your way writes.
"""

from __future__ import annotations

from pathlib import Path

from harness import ROOT
from harness.formats import CHECKPOINT_FIELDS, DURABILITY_MODES  # noqa: F401

DEFAULT = ROOT / "state" / "checkpoints.db"


class Checkpointer:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT)

    def save(self, run_id: str, checkpoint: dict, *, step, mode: str = "sync") -> None:
        raise NotImplementedError("Assignment 4, Part A: save one checkpoint")

    def last(self, run_id: str) -> dict | None:
        raise NotImplementedError("Assignment 4, Part B: the run's latest checkpoint, for a resume")

    def all(self, run_id: str) -> list[dict]:
        raise NotImplementedError("Assignment 4, Part A: every checkpoint the run saved, oldest first")

    def runs(self) -> list[str]:
        raise NotImplementedError("Assignment 4, Part A: every run_id with a checkpoint")
