"""Assignment 4, Part D: the memory store. This file is yours.

A store is shared by every run, keyed by repository and issue. It is durable: a
SQLite file such as state/store.db is fine. How you give a run an empty store, for
Part D's second set of five runs, is yours: an environment variable this module
reads, for example. The checker always reads your real store.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.5), so keep them:

    Store(path=None)                                  # None: your default file
    .write(record) -> id                              # a new record; returns its id
    .supersede(old_id, record) -> id                  # a new record that replaces old_id
    .active(repository, issue=None) -> list[dict]     # the active records, for retrieval
    .records() -> list[dict]                          # every record, active or not

Every record carries the fields of section 12.5: its kind (episodic, semantic or
procedural), its text, and its provenance: source, written_at, origin (derived or
ingested) and confirmed. A superseded record stays in the store, inactive, and the
record that replaced it names it in `supersedes`.
"""

from __future__ import annotations

from pathlib import Path

from harness import ROOT

DEFAULT = ROOT / "state" / "store.db"
REPOSITORY = "ledgerline"
KINDS = ("episodic", "semantic", "procedural")
ORIGINS = ("derived", "ingested")


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT)

    def write(self, record: dict):
        raise NotImplementedError("Assignment 4, Part D: write one record")

    def supersede(self, old_id, record: dict):
        raise NotImplementedError("Assignment 4, Part D: replace a record, keeping the old one inactive")

    def active(self, repository: str, issue: int | None = None) -> list[dict]:
        raise NotImplementedError("Assignment 4, Part D: the active records, for retrieval")

    def records(self) -> list[dict]:
        raise NotImplementedError("Assignment 4, Part D: every record, active or not")
