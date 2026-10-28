"""The mock issue tracker, and the mock remote that holds pull requests.

Issues are Markdown files in fixtures/issues/ (evaluation) and
fixtures/issues/dev/ (development), each with a small front-matter header. From
Assignment 4 an issue can carry its discussion: the comments people wrote on it,
under a "## Discussion" heading, one "### author · date" entry each (checks/
FORMATS.md, section 12.7). issue() returns them as `discussion`.
Comments and pull requests (PRs) live in a SQLite database, tracker/tracker.db
(checks/FORMATS.md, section 11.5, gives its tables).

Three rules hold for every write and every read:

- **Every write is stamped with the run_id of the run that made it**, by the
  harness, not the model. That stamp is what makes a run attributable.
- **Every read is scoped to one run.** A run sees only its own comments and PRs,
  so a check before a write in run 2 never finds run 1's PR. The model never sees
  a comment a run wrote: read_issue returns the issue and its fixture discussion.
- **A write may carry an idempotency key**, and the tracker accepts each key once:
  a unique constraint on the key column. A second write with a key the tracker has
  seen writes nothing and returns the first write's row, marked "replayed": true.

The tracker can lie, when a switch says so (harness/switches.py):

- FLAKY_WRITES=1: a write attempt times out about six times in ten. About five of
  those six had committed before the connection dropped; the other one never
  reached the tracker. Either way the caller gets TrackerTimeout, with the same
  words, and cannot tell which happened.
- READBACK_FAIL=1: once a write in a run has timed out, every read of that run's
  comments and PRs raises ReadbackUnavailable.

The tracker logs every write attempt it receives in its `attempts` table, and what
happened to it. That log is the tracker's, for counting and for the checker; your
harness must not read it to decide anything.

`make reset` archives the database to tracker/archive/ and starts empty; nothing is
ever deleted, and the checker reads the archives too.

    python -m harness.tracker reset    # archive tracker.db and start empty
"""

from __future__ import annotations

import random
import re
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from harness import ROOT
from harness import switches

_lock = threading.Lock()

# FLAKY_WRITES: the share of write attempts that time out, by when the connection drops.
FLAKY_RATES = {"before_commit": 0.1, "after_commit": 0.5}
TIMEOUT_MESSAGE = "the tracker did not answer in time"   # simulated: no real wait

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    body      TEXT NOT NULL,
    key       TEXT UNIQUE,
    posted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prs (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    branch    TEXT NOT NULL,
    title     TEXT NOT NULL,
    body      TEXT NOT NULL,
    draft     INTEGER NOT NULL DEFAULT 1,
    state     TEXT NOT NULL DEFAULT 'open',
    key       TEXT UNIQUE,
    opened_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    issue     INTEGER NOT NULL,
    key       TEXT,
    outcome   TEXT NOT NULL,
    row_id    INTEGER,
    at        TEXT NOT NULL
);
"""

# What the attempts table's outcome column says.
OUTCOMES = ("written", "replayed", "timeout_after_commit", "timeout_before_commit")


DISCUSSION = "## Discussion"
_ENTRY = re.compile(r"^###\s+(?P<author>[^\s(·]+)(?:\s*\((?P<role>[^)]*)\))?\s*·\s*(?P<date>\S+)\s*$", re.MULTILINE)


def parse_discussion(text: str) -> list[dict]:
    """An issue's discussion: [{author, role, date, body}], oldest first. `role` is what
    the fixture says in brackets after the name, such as maintainer, or None."""
    entries = list(_ENTRY.finditer(text))
    out = []
    for i, m in enumerate(entries):
        end = entries[i + 1].start() if i + 1 < len(entries) else len(text)
        out.append({"author": m["author"], "role": m["role"], "date": m["date"],
                    "body": text[m.end():end].strip()})
    return out


class IssueNotFound(KeyError):
    pass


class TrackerTimeout(TimeoutError):
    """A write timed out. It may or may not have happened: nothing in the error says which."""


class ReadbackUnavailable(ConnectionError):
    """READBACK_FAIL: a read of this run's writes failed, after one of its writes timed out."""


class Tracker:
    def __init__(self, root: Path | None = None, state_dir: Path | None = None, *,
                 flaky: bool | None = None, readback_fail: bool | None = None,
                 faults: list[str | None] | None = None, seed: int | None = None):
        """`flaky` and `readback_fail` default to the switches. `faults`, for tests and
        the checker, decides write attempts in order instead of chance: each entry is
        None (the write goes through), "before_commit" or "after_commit"; once the
        list is used up, writes go through (or, with `flaky`, take their chance)."""
        self.root = Path(root or ROOT)
        self.issue_dir = self.root / "fixtures" / "issues"
        self.state_dir = Path(state_dir or self.root / "tracker")
        self.db_path = self.state_dir / "tracker.db"
        on = switches.current()
        self.flaky = on["flaky_writes"] if flaky is None else flaky
        self.readback_fail = on["readback_fail"] if readback_fail is None else readback_fail
        self.faults = list(faults) if faults is not None else None
        self._rng = random.Random(seed)
        self._timed_out: set[str] = set()   # runs with a write that timed out (READBACK_FAIL)
        self.on_commit = None                # the runner's: called (run_id, kind) once a write commits

    # -- issues -------------------------------------------------------------------
    def _issue_path(self, number: int) -> Path:
        for candidate in (self.issue_dir / f"{number}.md", self.issue_dir / "dev" / f"{number}.md"):
            if candidate.exists():
                return candidate
        raise IssueNotFound(number)

    def issue(self, number: int) -> dict:
        text = self._issue_path(int(number)).read_text()
        _, header, body = text.split("---", 2)
        meta = yaml.safe_load(header)
        body, _, rest = body.partition(DISCUSSION)
        return {**meta, "body": body.strip(), "discussion": parse_discussion(rest)}

    def issue_numbers(self, which: str = "eval") -> list[int]:
        folder = self.issue_dir / "dev" if which == "dev" else self.issue_dir
        return sorted(int(p.stem) for p in folder.glob("*.md"))

    # -- the database ---------------------------------------------------------------
    @contextmanager
    def _connect(self):
        """One connection, committed and closed when the block ends."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.executescript(SCHEMA)
            yield db
            db.commit()
        finally:
            db.close()

    def _fault(self) -> str | None:
        with _lock:
            if self.faults:
                return self.faults.pop(0)
            if not self.flaky:
                return None
            roll = self._rng.random()
        if roll < FLAKY_RATES["before_commit"]:
            return "before_commit"
        if roll < FLAKY_RATES["before_commit"] + FLAKY_RATES["after_commit"]:
            return "after_commit"
        return None

    def _write(self, run_id: str, kind: str, issue: int, key: str | None, insert) -> dict:
        """One write attempt: the fault, the key's unique constraint, the attempts log."""
        fault = self._fault()
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with _lock, self._connect() as db:
            if fault == "before_commit":
                db.execute("INSERT INTO attempts (run_id, kind, issue, key, outcome, row_id, at) "
                           "VALUES (?, ?, ?, ?, ?, NULL, ?)", (run_id, kind, issue, key, "timeout_before_commit", stamp))
                row = None
            else:
                table = "comments" if kind == "comment" else "prs"
                existing = (db.execute(f"SELECT * FROM {table} WHERE key = ?", (key,)).fetchone()
                            if key is not None else None)
                if existing is not None:
                    row, outcome = {**dict(existing), "replayed": True}, "replayed"
                else:
                    row, outcome = {**insert(db, stamp), "replayed": False}, "written"
                if fault == "after_commit":
                    outcome = "timeout_after_commit"
                db.execute("INSERT INTO attempts (run_id, kind, issue, key, outcome, row_id, at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, kind, issue, key, outcome, row["id"], stamp))
        if fault != "before_commit" and self.on_commit is not None:
            self.on_commit(run_id, kind)    # the write is committed; run.py --die-during-step stops here
        if fault is not None:
            self._timed_out.add(run_id)
            raise TrackerTimeout(TIMEOUT_MESSAGE)
        return row

    def _readable(self, run_id: str) -> None:
        if not run_id:
            raise TypeError("every read is scoped to one run: pass its run_id")
        if self.readback_fail and run_id in self._timed_out:
            raise ReadbackUnavailable("the tracker could not be read; try again later")

    def _rows(self, sql: str, args: tuple) -> list[dict]:
        if not self.db_path.exists():
            return []
        with self._connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

    # -- comments -----------------------------------------------------------------
    def post_comment(self, run_id: str, number: int, body: str, key: str | None = None) -> dict:
        self._issue_path(int(number))  # refuse comments on issues that do not exist

        def insert(db, stamp):
            cur = db.execute("INSERT INTO comments (run_id, issue, body, key, posted_at) VALUES (?, ?, ?, ?, ?)",
                             (run_id, int(number), body, key, stamp))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(number), "body": body, "key": key,
                    "posted_at": stamp}
        return self._write(run_id, "comment", int(number), key, insert)

    def comments(self, run_id: str, issue: int | None = None) -> list[dict]:
        """This run's comments, oldest first; on one issue if `issue` is given."""
        self._readable(run_id)
        if issue is None:
            return self._rows("SELECT * FROM comments WHERE run_id = ? ORDER BY id", (run_id,))
        return self._rows("SELECT * FROM comments WHERE run_id = ? AND issue = ? ORDER BY id", (run_id, int(issue)))

    def comment_by_key(self, run_id: str, key: str) -> dict | None:
        """This run's comment written with this key, or None."""
        self._readable(run_id)
        rows = self._rows("SELECT * FROM comments WHERE run_id = ? AND key = ?", (run_id, key))
        return rows[0] if rows else None

    # -- pull requests ----------------------------------------------------------------
    def open_pr(self, run_id: str, number: int, branch: str, title: str, body: str,
                key: str | None = None) -> dict:
        """Open a draft PR from `branch` for issue `number`. The mock remote needs no commits."""
        self._issue_path(int(number))
        if not str(branch).strip() or not str(title).strip():
            raise ValueError("a pull request needs a branch and a title")

        def insert(db, stamp):
            cur = db.execute("INSERT INTO prs (run_id, issue, branch, title, body, key, opened_at) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, int(number), branch, title, body, key, stamp))
            return {"id": cur.lastrowid, "run_id": run_id, "issue": int(number), "branch": branch, "title": title,
                    "body": body, "draft": 1, "state": "open", "key": key, "opened_at": stamp}
        return self._write(run_id, "pr", int(number), key, insert)

    def prs(self, run_id: str, branch: str | None = None, state: str | None = "open") -> list[dict]:
        """This run's PRs, oldest first: open ones unless `state` says otherwise (None for all)."""
        self._readable(run_id)
        sql, args = "SELECT * FROM prs WHERE run_id = ?", [run_id]
        if branch is not None:
            sql, args = sql + " AND branch = ?", args + [branch]
        if state is not None:
            sql, args = sql + " AND state = ?", args + [state]
        return self._rows(sql + " ORDER BY id", tuple(args))

    def pr_by_key(self, run_id: str, key: str) -> dict | None:
        """This run's PR opened with this key, or None."""
        self._readable(run_id)
        rows = self._rows("SELECT * FROM prs WHERE run_id = ? AND key = ?", (run_id, key))
        return rows[0] if rows else None

    # -- the whole database, for the runner and the checkers --------------------------
    def table(self, name: str) -> list[dict]:
        """Every row of comments, prs or attempts, every run's. Not for your harness."""
        if name not in ("comments", "prs", "attempts"):
            raise ValueError(f"no table {name!r}")
        return self._rows(f"SELECT * FROM {name} ORDER BY id", ())

    def remove_runs(self, run_ids: set[str]) -> dict[str, list[dict]]:
        """Delete these runs' rows from every table and return them (run.py --discard)."""
        out: dict[str, list[dict]] = {}
        if not self.db_path.exists() or not run_ids:
            return out
        marks = ",".join("?" * len(run_ids))
        with _lock, self._connect() as db:
            for name in ("comments", "prs", "attempts"):
                rows = db.execute(f"SELECT * FROM {name} WHERE run_id IN ({marks})", tuple(run_ids)).fetchall()
                out[name] = [dict(r) for r in rows]
                db.execute(f"DELETE FROM {name} WHERE run_id IN ({marks})", tuple(run_ids))
        return out

    def reset(self) -> Path | None:
        """Archive the database and start empty. Returns the archive path."""
        if not self.db_path.exists():
            return None
        archive = self.state_dir / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / f"tracker-{time.strftime('%Y%m%d-%H%M%S')}.db"
        shutil.move(str(self.db_path), target)
        return target


if __name__ == "__main__":
    if sys.argv[1:] == ["reset"]:
        moved = Tracker().reset()
        print(f"tracker reset; the old database archived to {moved}" if moved else "tracker already empty")
    else:
        print(__doc__)
