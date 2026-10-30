"""Assignment 4, Part D: the memory store. This file is yours.

A store is shared by every run, keyed by repository and issue. It is durable: one
SQLite file, state/store.db. The rules for what goes in, with which tags, and what
leaves, are in state/write_policy.md; this module enforces the ones code can.

A run with REPOMIND_STORE=empty gets an empty store: an in-memory database that
starts with no records and is gone when the run ends, so it reads nothing and its
writes reach no other run. The checker always reads the real store.

The checker calls these, with these exact signatures (checks/FORMATS.md, section
12.5), so keep them:

    Store(path=None)                                  # None: your default file
    .write(record) -> id                              # a new record; returns its id
    .supersede(old_id, record) -> id                  # a new record that replaces old_id
    .active(repository, issue=None) -> list[dict]     # the active records, for retrieval
    .records() -> list[dict]                          # every record, active or not

One more, for retrieval on a topic (Part E's contradiction test):

    .search(repository, pattern, issue=None) -> list[dict]   # active records whose text matches

A superseded record stays in the store, inactive, and the record that replaced it
names it in `supersedes`. Eviction (write_policy.md) deletes only RepoMind's own
episodic notes, oldest first, once more than MAX_EPISODIC are active.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from harness import ROOT

DEFAULT = ROOT / "state" / "store.db"
EMPTY = "empty"                       # REPOMIND_STORE=empty: a run with an empty store
REPOSITORY = "ledgerline"
KINDS = ("episodic", "semantic", "procedural")
ORIGINS = ("derived", "ingested")
SOURCE = re.compile(r"^(user|repo|memory|issue:\d+)$")
MAX_EPISODIC = 200                    # active episodic records per repository; see write_policy.md, Eviction
FIELDS = ("id", "repository", "issue", "kind", "text", "source", "written_at", "origin", "confirmed",
          "active", "supersedes", "stated_by")

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repository  TEXT    NOT NULL,
    issue       INTEGER,
    kind        TEXT    NOT NULL CHECK (kind IN ('episodic', 'semantic', 'procedural')),
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    written_at  TEXT    NOT NULL,
    origin      TEXT    NOT NULL CHECK (origin IN ('derived', 'ingested')),
    confirmed   INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    supersedes  INTEGER REFERENCES records(id),
    stated_by   TEXT
);
CREATE INDEX IF NOT EXISTS records_scope ON records (repository, issue, active);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty() -> bool:
    """Whether this process runs with an empty store (REPOMIND_STORE=empty)."""
    return os.environ.get("REPOMIND_STORE", "").strip().lower() == EMPTY


class Store:
    def __init__(self, path: Path | str | None = None):
        if path is None and empty():
            path = ":memory:"
        self.path = path if path == ":memory:" else Path(path or DEFAULT)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    # -- writing -----------------------------------------------------------------------------
    def write(self, record: dict):
        """A new record, checked against write_policy.md's tags; returns its id."""
        with self.db:
            new = self._insert(record, supersedes=None)
            self._evict(record.get("repository") or REPOSITORY)
        return new

    def supersede(self, old_id, record: dict):
        """A new record that replaces old_id: the old one stays, inactive."""
        with self.db:
            old = self.db.execute("SELECT active FROM records WHERE id = ?", (old_id,)).fetchone()
            if old is None:
                raise KeyError(f"no record {old_id!r} to supersede")
            if not old["active"]:
                raise ValueError(f"record {old_id!r} is already inactive")
            self.db.execute("UPDATE records SET active = 0 WHERE id = ?", (old_id,))
            new = self._insert(record, supersedes=old_id)
        return new

    def _insert(self, record: dict, supersedes) -> int:
        r = {"repository": REPOSITORY, "issue": None, "written_at": now(), "confirmed": False,
             "stated_by": None, **record}
        problems = []
        if r["kind"] not in KINDS:
            problems.append(f"kind {r['kind']!r}")
        if r.get("origin") not in ORIGINS:
            problems.append(f"origin {r.get('origin')!r}")
        if not SOURCE.match(str(r.get("source") or "")):
            problems.append(f"source {r.get('source')!r}")
        if not isinstance(r["confirmed"], bool):
            problems.append(f"confirmed {r['confirmed']!r}")
        try:
            datetime.fromisoformat(str(r["written_at"]).replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"written_at {r['written_at']!r}")
        if not str(r.get("text") or "").strip():
            problems.append("no text")
        # The policy's one hard rule: what anyone can write is never stored as a fact.
        if str(r.get("source")).startswith("issue:") and (r["kind"] == "semantic" or r["confirmed"]):
            problems.append("an issue's text is stored unconfirmed, and never as semantic")
        if problems:
            raise ValueError("record breaks the write policy: " + ", ".join(problems))
        cur = self.db.execute(
            "INSERT INTO records (repository, issue, kind, text, source, written_at, origin, confirmed, active,"
            " supersedes, stated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (r["repository"], r["issue"], r["kind"], r["text"], r["source"], r["written_at"], r["origin"],
             int(r["confirmed"]), supersedes, r["stated_by"]))
        return cur.lastrowid

    def _evict(self, repository: str) -> None:
        """Past MAX_EPISODIC active episodic records, delete RepoMind's own oldest
        unconfirmed ones. Nothing a person stated, and nothing confirmed, is evicted."""
        rows = self.db.execute(
            "SELECT id FROM records WHERE repository = ? AND kind = 'episodic' AND active = 1 "
            "ORDER BY written_at DESC, id DESC", (repository,)).fetchall()
        extra = [r["id"] for r in rows[MAX_EPISODIC:]]
        evictable = [i for i in extra if self.db.execute(
            "SELECT 1 FROM records WHERE id = ? AND source = 'memory' AND confirmed = 0", (i,)).fetchone()]
        for i in evictable:
            self.db.execute("UPDATE records SET supersedes = NULL WHERE supersedes = ?", (i,))
            self.db.execute("DELETE FROM records WHERE id = ?", (i,))

    # -- reading -----------------------------------------------------------------------------
    def active(self, repository: str, issue: int | None = None) -> list[dict]:
        """With no issue, every active record of the repository; with one, that issue's
        and every repository-wide one (issue null). Oldest first."""
        if issue is None:
            rows = self.db.execute("SELECT * FROM records WHERE repository = ? AND active = 1 ORDER BY id",
                                   (repository,))
        else:
            rows = self.db.execute("SELECT * FROM records WHERE repository = ? AND active = 1 "
                                   "AND (issue = ? OR issue IS NULL) ORDER BY id", (repository, int(issue)))
        return [self._dict(r) for r in rows]

    def search(self, repository: str, pattern: str, issue: int | None = None) -> list[dict]:
        """The active records whose text matches pattern (a regular expression, any case)."""
        found = re.compile(pattern, re.IGNORECASE)
        return [r for r in self.active(repository, issue) if found.search(r["text"])]

    def records(self) -> list[dict]:
        return [self._dict(r) for r in self.db.execute("SELECT * FROM records ORDER BY id")]

    def latest(self, repository: str, issue: int, kind: str, source: str) -> dict | None:
        """The active record of this issue, kind and source, if there is one."""
        row = self.db.execute("SELECT * FROM records WHERE repository = ? AND issue = ? AND kind = ? AND source = ? "
                              "AND active = 1 ORDER BY id DESC LIMIT 1", (repository, issue, kind, source)).fetchone()
        return self._dict(row) if row else None

    @staticmethod
    def _dict(row: sqlite3.Row) -> dict:
        d = {k: row[k] for k in FIELDS}
        d["confirmed"], d["active"] = bool(d["confirmed"]), bool(d["active"])
        if d["stated_by"] is None:
            del d["stated_by"]
        return d

    def close(self) -> None:
        self.db.close()
