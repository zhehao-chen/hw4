"""Assignment 4, Part A: the checkpointer.

A checkpointer saves one run's state, keyed by the run's run_id (one run's line of
checkpoints is a thread). The backend is a SQLite file, state/checkpoints.db: it
outlives the process, which an in-memory store would not.

The checker calls these, with these exact signatures (checks/FORMATS.md, 12.4):

    Checkpointer(path=None)                    # None: state/checkpoints.db
    .save(run_id, checkpoint, *, step, mode)   # one checkpoint; mode is sync, async or exit
    .last(run_id) -> dict | None               # the run's latest checkpoint, or None
    .all(run_id) -> list[dict]                 # every checkpoint the run saved, oldest first
    .runs() -> list[str]                       # every run_id that has a checkpoint

The three durability modes (slide 12) say how save() writes:

    sync   written and committed before save() returns (SQLite's synchronous=FULL
           fsyncs on commit). RepoMind runs in this mode: it has irreversible steps.
    async  serialized now, written on a background thread; a crash before the
           thread commits loses it.
    exit   kept in memory and written when the process exits (or flush() is
           called); a crash loses every one of them.

A checkpoint is serialized to JSON the moment save() is called, so a later change to
the dicts the way passed in never changes what was saved.
"""

from __future__ import annotations

import atexit
import json
import sqlite3
import threading
import time
from pathlib import Path

from harness import ROOT
from harness.formats import CHECKPOINT_FIELDS, DURABILITY_MODES

DEFAULT = ROOT / "state" / "checkpoints.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT NOT NULL,
    step     TEXT,
    mode     TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    body     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checkpoints_run ON checkpoints (run_id, seq);
"""


class Checkpointer:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or DEFAULT)
        self._buffer: list[tuple] = []           # exit mode: written at exit
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._exit_hook = False

    # -- storage ---------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(SCHEMA)
        return db

    def _write(self, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            db = self._connect()
            try:
                with db:   # one transaction, committed (and fsynced) on leaving the block
                    db.executemany("INSERT INTO checkpoints (run_id, step, mode, saved_at, body) "
                                   "VALUES (?, ?, ?, ?, ?)", rows)
            finally:
                db.close()

    def flush(self) -> None:
        """Wait for every async save, and write every exit-mode save."""
        for thread in self._threads:
            thread.join()
        self._threads.clear()
        rows, self._buffer = self._buffer, []
        self._write(rows)

    # -- the interface ---------------------------------------------------------------
    def save(self, run_id: str, checkpoint: dict, *, step, mode: str = "sync") -> None:
        if mode not in DURABILITY_MODES:
            raise ValueError(f"mode is one of {DURABILITY_MODES}, not {mode!r}")
        if not isinstance(checkpoint, dict) or set(checkpoint) != set(CHECKPOINT_FIELDS):
            raise ValueError(f"a checkpoint has exactly the fields {CHECKPOINT_FIELDS}")
        body = json.dumps(checkpoint, sort_keys=True)          # fails here if anything does not serialize
        row = (run_id, None if step is None else str(step), mode, time.strftime("%Y-%m-%dT%H:%M:%S%z"), body)
        if mode == "sync":
            self._write([row])                                 # on disk before we return
        elif mode == "async":
            thread = threading.Thread(target=self._write, args=([row],), daemon=True)
            thread.start()
            self._threads.append(thread)
        else:
            self._buffer.append(row)
            if not self._exit_hook:
                atexit.register(self.flush)
                self._exit_hook = True

    def _rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        if not self.path.exists():
            return []
        db = self._connect()
        try:
            return db.execute(sql, args).fetchall()
        finally:
            db.close()

    def last(self, run_id: str) -> dict | None:
        self.flush()
        rows = self._rows("SELECT body FROM checkpoints WHERE run_id = ? ORDER BY seq DESC LIMIT 1", (run_id,))
        return json.loads(rows[0][0]) if rows else None

    def all(self, run_id: str) -> list[dict]:
        self.flush()
        return [json.loads(b) for (b,) in
                self._rows("SELECT body FROM checkpoints WHERE run_id = ? ORDER BY seq", (run_id,))]

    def runs(self) -> list[str]:
        self.flush()
        return [r for (r,) in self._rows("SELECT run_id FROM checkpoints GROUP BY run_id ORDER BY MIN(seq)")]

    def size(self, run_id: str) -> int:
        """The bytes one run's checkpoints take together: the summed length of what was saved (Part E)."""
        rows = self._rows("SELECT COALESCE(SUM(LENGTH(CAST(body AS BLOB))), 0) FROM checkpoints WHERE run_id = ?",
                          (run_id,))
        return int(rows[0][0]) if rows else 0
