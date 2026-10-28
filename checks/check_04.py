#!/usr/bin/env python3
"""Assignment 4 checker. Run it with `make check-04`.

It reads only the environment: your runs/ traces and the request records the harness
keeps on issues 4191 and 4192, the tracker's database and every archive of it, your
checkpointer and your store through the interfaces of checks/FORMATS.md, sections
12.4 and 12.5, and reports/LAB_04.json. It never asks a model anything and never
trusts a model's words.

Assignment 4 is scored out of 100. The checker awards the automated 82; staff read
the report for the other 18. It also prints integrity flags, which carry no points
and go to staff for review. Every format it reads is defined in checks/FORMATS.md,
section 12.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sqlite3
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from harness import LAB  # noqa: E402
from harness.backends import REAL_BACKENDS  # noqa: E402
from harness.formats import (CHECKPOINT_FIELDS, RECORDED_ISSUES, normalize_path,  # noqa: E402
                             parse_triage_comment, request_text, squeeze)
from harness.roles import WRITES, role_of  # noqa: E402
from harness.runner import is_free, is_trace  # noqa: E402
from harness.trace import read_trace  # noqa: E402

MATRIX_ISSUE, REOPENED, CLAIM_ISSUE = 4201, 4207, 4188
REPOSITORY = "ledgerline"
BRANCH = f"repomind/issue-{MATRIX_ISSUE}"
CLAIM = re.compile(r"auto[\s-]*merg", re.IGNORECASE)
RULE = re.compile(r"duplicate", re.IGNORECASE)
SOURCE = re.compile(r"^(user|repo|memory|issue:\d+)$")
CONVERSATION_KEYS = {"conversation", "messages", "history", "transcript"}
RUNS_PER_SET = 5
CASES = ("attention", "compaction", "session")   # Part F's three forgettings
# The harness files a kill, a resume and the request record depend on, hashed: a change to one is an integrity flag.
HARNESS_SHA = {"run.py": "74a2a467ed0e949d", "harness/runner.py": "fc9643ae38c3d0b6", "harness/tracker.py": "403309672e7c63e6",
               "harness/trace.py": "b220759b3dc612b4", "harness/client.py": "c9f8f98a33cb7293"}


@dataclass
class Section:
    name: str
    possible: float
    earned: float = 0.0
    notes: list[str] = field(default_factory=list)
    manual: bool = False

    def note(self, text: str) -> None:
        self.notes.append(text)


def raised(what: str) -> str:
    return f"{what} raised:\n" + traceback.format_exc(limit=3)


def sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


# -- the environment ---------------------------------------------------------------------------------

@dataclass
class Run:
    run_id: str
    start: dict
    records: list[dict]
    mtime: float

    @property
    def issue(self) -> int | None:
        return self.start.get("issue")

    @property
    def die(self) -> dict | None:
        return self.start.get("die") or None

    @property
    def key_mode(self) -> str:
        return (self.start.get("switches") or {}).get("key_mode") or "derived"

    @property
    def resume_at(self) -> int | None:
        return next((i for i, r in enumerate(self.records) if r.get("type") == "resume"), None)

    @property
    def finished(self) -> bool:
        return any(r.get("type") == "run_end" for r in self.records)

    @property
    def crashed(self) -> list[dict]:
        at = self.resume_at
        return self.records if at is None else self.records[:at]

    @property
    def resumed(self) -> list[dict]:
        at = self.resume_at
        return [] if at is None else self.records[at + 1:]

    def lines(self, kind: str, records=None) -> list[dict]:
        return [r for r in (self.records if records is None else records) if r.get("type") == kind]

    @property
    def order(self) -> tuple:
        return (self.start.get("started") or "", self.mtime)


def load_runs() -> tuple[list[Run], list[str], int]:
    runs, notes, scripted = [], [], 0
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if not is_trace(path):
            continue
        try:
            records = read_trace(path)
        except json.JSONDecodeError:
            notes.append(f"{path.name}: not valid JSON lines, skipped")
            continue
        start = records[0] if records and records[0].get("type") == "run_start" else None
        if not start or start.get("lab") != LAB or start.get("way") != "planned":
            continue
        if is_free(start.get("backend") or ""):
            scripted += 1
            continue
        runs.append(Run(start.get("run_id") or path.stem, start, records, path.stat().st_mtime))
    return runs, notes, scripted


class Writes:
    """Every comment and PR in the tracker's database and its archives, by run_id."""

    def __init__(self):
        self.comments: dict[str, list[dict]] = {}
        self.prs: dict[str, list[dict]] = {}
        self.files = [p for p in [ROOT / "tracker" / "tracker.db", *sorted((ROOT / "tracker" / "archive").glob("*.db"))]
                      if p.exists()]
        for path in self.files:
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            try:
                for table, out in (("comments", self.comments), ("prs", self.prs)):
                    for row in db.execute(f"SELECT * FROM {table} ORDER BY id"):
                        out.setdefault(row["run_id"], []).append(dict(row))
            except sqlite3.DatabaseError:
                pass
            finally:
                db.close()

    def on_issue(self, run_id: str, issue: int) -> list[dict]:
        return [c for c in self.comments.get(run_id, []) if c["issue"] == issue]

    def open_prs(self, run_id: str, branch: str) -> list[dict]:
        return [p for p in self.prs.get(run_id, []) if p["branch"] == branch and p["state"] == "open"]


def state_module(name: str):
    return importlib.import_module(f"state.{name}")


def checkpoints_of(runs: list[Run]) -> tuple[dict[str, list[dict]] | None, str | None]:
    try:
        cp = state_module("checkpointer").Checkpointer()
        return {r.run_id: list(cp.all(r.run_id) or []) for r in runs}, None
    except NotImplementedError:
        return None, "state/checkpointer.py: Checkpointer.all is not written yet"
    except Exception:
        return None, raised("state/checkpointer.py, Checkpointer().all(run_id)")


def as_booleans(record) -> dict:
    """SQLite stores true and false as 1 and 0: read them back as booleans."""
    out = dict(record) if isinstance(record, dict) else {}
    for name in ("confirmed", "active"):
        if not isinstance(out.get(name), bool) and out.get(name) in (0, 1):
            out[name] = bool(out[name])
    return out


class Booleans:
    """The student's store, with each record's 0 and 1 read as false and true."""

    def __init__(self, store):
        self._store = store

    def active(self, *args):
        return [as_booleans(r) for r in self._store.active(*args) or []]


def store_records() -> tuple[list[dict] | None, object, str | None]:
    try:
        store = state_module("store").Store()
        return [as_booleans(r) for r in store.records() or []], Booleans(store), None
    except NotImplementedError:
        return None, None, "state/store.py: Store.records is not written yet"
    except Exception:
        return None, None, raised("state/store.py, Store().records()")


# -- 1. Checkpoint contents ------------------------------------------------------------------------

def has_conversation(node) -> bool:
    if isinstance(node, dict):
        if CONVERSATION_KEYS & {str(k).lower() for k in node}:
            return True
        if "role" in node and "content" in node:
            return True
        return any(has_conversation(v) for v in node.values())
    if isinstance(node, list):
        return any(has_conversation(v) for v in node)
    return False


def checkpoint_problem(cp) -> str | None:
    if not isinstance(cp, dict):
        return f"a checkpoint is {type(cp).__name__}, not a dict"
    if set(cp) != set(CHECKPOINT_FIELDS):
        return f"fields {sorted(cp)}; want exactly {list(CHECKPOINT_FIELDS)}"
    calls = cp.get("completed_calls")
    if not isinstance(calls, list) or not all(isinstance(c, dict) and "key" in c for c in calls):
        return "completed_calls must be a list of entries, each with a key"
    for c in calls:
        if role_of(str(c.get("tool"))) in WRITES and not c.get("key"):
            return f"a write in completed_calls ({c.get('tool')}) has no key"
    if has_conversation(cp):
        return "it holds the conversation"
    try:
        json.dumps(cp)
    except (TypeError, ValueError):
        return "it does not serialize to JSON"
    return None


def check_contents(runs: list[Run], cps: dict | None, why: str | None) -> Section:
    s = Section("Checkpoint contents", 6)
    if cps is None:
        s.note(why or "no checkpoints")
        return s
    judged = [r for r in runs if cps.get(r.run_id) or r.lines("checkpoint")]
    good, bad = 0, []
    for run in judged:
        saved = cps.get(run.run_id) or []
        if not saved:
            bad.append(f"{run.run_id}: checkpoint lines in its trace, and no checkpoint saved")
            continue
        synced = sum(1 for r in run.lines("checkpoint") if r.get("mode") == "sync")
        if len(saved) < synced:
            bad.append(f"{run.run_id}: {synced} sync checkpoint lines in its trace, and {len(saved)} checkpoints saved")
            continue
        problem = next((p for p in map(checkpoint_problem, saved) if p), None)
        if problem:
            bad.append(f"{run.run_id}: {problem}")
        else:
            good += 1
    if not judged:
        s.note("no run saved a checkpoint yet (Part A)")
        return s
    s.earned = round(6 * good / len(judged), 2)
    if bad:
        s.note(f"{len(bad)} of {len(judged)} runs' checkpoints fail, e.g. " + "; ".join(bad[:3]))
    return s


# -- 2. Sync before writes ---------------------------------------------------------------------------

def check_sync(runs: list[Run]) -> Section:
    s = Section("Sync before writes", 8)
    total = good = 0
    bad = []
    for run in runs:
        last_cp, since = None, set()   # the plan steps of the tool calls since the latest checkpoint
        for r in run.records:
            kind = r.get("type")
            if kind == "run_start":
                last_cp, since = None, set()
            elif kind == "resume":
                # The crashed half's checkpoint is on disk, and a resume replays from it. A write
                # killed just after it returned is replayed too: its first call is not one between.
                if last_cp is not None and since <= {str(last_cp.get("step"))}:
                    since = set()
            elif kind == "checkpoint":
                last_cp, since = r, set()
            elif kind == "tool_call":
                if role_of(str(r.get("name"))) in WRITES:
                    total += 1
                    if last_cp is None or since:
                        bad.append(f"{run.run_id}: {r.get('name')} (plan step {r.get('plan_step')}) with no "
                                   "checkpoint line just before it")
                    elif last_cp.get("mode") != "sync":
                        bad.append(f"{run.run_id}: {r.get('name')} after a {last_cp.get('mode')!r} checkpoint")
                    elif str(last_cp.get("step")) != str(r.get("plan_step")):
                        bad.append(f"{run.run_id}: {r.get('name')} for plan step {r.get('plan_step')} after a "
                                   f"checkpoint for step {last_cp.get('step')}")
                    else:
                        good += 1
                since.add(str(r.get("plan_step")))
    if not total:
        s.note("no write in any run of this assignment yet")
        return s
    s.earned = round(8 * good / total, 2)
    if bad:
        s.note(f"{len(bad)} of {total} writes without a sync checkpoint just before them, e.g. " + "; ".join(bad[:3]))
    return s


# -- 3. Resume, not restart --------------------------------------------------------------------------

def call_id(r: dict) -> tuple:
    return (str(r.get("plan_step")), r.get("name"), json.dumps(r.get("input"), sort_keys=True))


def check_resume(runs: list[Run]) -> Section:
    s = Section("Resume, not restart", 8)
    judged, bad = [], []
    for run in runs:
        if run.resume_at is None:
            continue
        crashed = run.crashed
        last = max((i for i, r in enumerate(crashed) if r.get("type") == "checkpoint"), default=None)
        if last is None:
            continue
        judged.append(run)
        done = {call_id(r) for r in crashed[:last] if r.get("type") == "tool_call"}
        again = [r for r in run.lines("tool_call", run.resumed) if call_id(r) in done]
        if again:
            bad.append(f"{run.run_id}: after its resume line it calls {again[0].get('name')} for plan step "
                       f"{again[0].get('plan_step')} again, a call that completed before its last checkpoint")
    if not judged:
        s.note("no resumed run whose crashed half saved a checkpoint (Part B)")
        return s
    s.earned = round(8 * (len(judged) - len(bad)) / len(judged), 2)
    if bad:
        s.note(f"{len(bad)} of {len(judged)} resumed runs repeat finished work, e.g. " + "; ".join(bad[:3]))
    return s


# -- 4 and 5. The crash matrices -----------------------------------------------------------------------

def plan_steps(run: Run) -> int:
    seen = []
    for r in run.lines("tool_call"):
        step = r.get("plan_step")
        if step is not None and str(step) not in seen:
            seen.append(str(step))
    return len(seen)


def cells(runs: list[Run], key_mode: str) -> dict[tuple[str, int], Run]:
    """The latest killed run per (when, step), with these keys, on the matrix issue."""
    out: dict[tuple[str, int], Run] = {}
    for run in runs:
        die = run.die
        if run.issue != MATRIX_ISSUE or not die or run.key_mode != key_mode:
            continue
        key = (die.get("when"), int(die.get("step") or 0))
        if key not in out or run.order > out[key].order:
            out[key] = run
    return out


def uncrashed(runs: list[Run], report: dict) -> tuple[Run | None, str | None]:
    want = report.get("uncrashed_run_id")
    if not want:
        return None, "reports/LAB_04.json has no uncrashed_run_id (Part B, task 3)"
    run = next((r for r in runs if r.run_id == want), None)
    if run is None:
        return None, (f"uncrashed_run_id {want!r} is not a run of this assignment on your model in runs/ "
                      "(scripted runs are left out)")
    if run.issue != MATRIX_ISSUE or run.die or not run.finished or run.resume_at is not None:
        return None, f"uncrashed_run_id {want!r} is not a finished, uncrashed run of issue {MATRIX_ISSUE}"
    return run, None


def cell_result(run: Run, writes: Writes, cps: dict | None) -> tuple[bool, str]:
    if run.resume_at is None:
        return False, "never killed and resumed" if run.finished else "killed, and not resumed yet"
    if not run.finished:
        return False, "resumed, and not finished"
    comments = writes.on_issue(run.run_id, MATRIX_ISSUE)
    prs = writes.open_prs(run.run_id, BRANCH)
    if len(comments) != 1:
        return False, f"{len(comments)} comments on {MATRIX_ISSUE}"
    if len(prs) > 1:
        return False, f"{len(prs)} open PRs from {BRANCH}"
    saved = (cps or {}).get(run.run_id) or []
    findings = saved[-1].get("findings") if saved and isinstance(saved[-1], dict) else None
    if not isinstance(findings, dict) or "file" not in findings or "label" not in findings:
        return False, "its last checkpoint's findings have no label and file"
    label, file = parse_triage_comment(comments[0]["body"])
    want_file = normalize_path(str(findings.get("file")))
    if (label, file) != (str(findings.get("label")).lower(), want_file):
        return False, f"its comment says {label}, {file}; its findings {findings.get('label')}, {findings.get('file')}"
    if len(prs) != (0 if want_file == "none" else 1):
        return False, f"{len(prs)} open PRs, and its findings' file is {findings.get('file')}"
    return True, ""


def check_derived(runs: list[Run], report: dict, writes: Writes, cps: dict | None, why: str | None) -> Section:
    s = Section("Crash matrix, derived keys", 20)
    base, problem = uncrashed(runs, report)
    if base is None:
        s.note(problem)
        return s
    steps = plan_steps(base)
    found = cells(runs, "derived")
    if cps is None:
        s.note(why or "no checkpoints to read findings from")
    passed, notes = 0, []
    for k in range(1, steps + 1):
        for when in ("after", "during"):
            run = found.get((when, k))
            if run is None:
                notes.append(f"{when} step {k}: no run")
                continue
            ok, why_not = cell_result(run, writes, cps)
            passed += ok
            if not ok:
                notes.append(f"{when} step {k} ({run.run_id}): {why_not}")
    s.earned = round(20 * passed / (2 * steps), 2) if steps else 0
    if notes:
        s.note(f"{passed} of {2 * steps} cases pass (steps 1 to {steps}, after and during); " + "; ".join(notes[:4]))
    return s


def check_uuid(runs: list[Run], report: dict, writes: Writes) -> Section:
    s = Section("Crash matrix, random keys", 6)
    found = cells(runs, "uuid")
    dup = {run.run_id: sorted(str(c["id"]) for c in writes.on_issue(run.run_id, MATRIX_ISSUE))
           for run in found.values() if run.finished and len(writes.on_issue(run.run_id, MATRIX_ISSUE)) >= 2}
    if not found:
        s.note("no Part C cases: KEY_MODE=uuid python run.py --way planned --issues 4201 --die-after-step N")
        return s
    if dup:
        s.earned += 3
    else:
        s.note(f"{len(found)} Part C cases, none with a second comment for its run_id")
        return s
    cited = report.get("duplicate_comment_ids") if isinstance(report.get("duplicate_comment_ids"), dict) else {}
    cited = {k: sorted(str(i) for i in (v or [])) for k, v in cited.items()}
    if cited == dup:
        s.earned += 3
    else:
        s.note(f"reports/LAB_04.json duplicate_comment_ids is {cited}; the tracker holds {dup}")
    return s


# -- 6, 7 and 8. The store ---------------------------------------------------------------------------

def iso(value) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def check_provenance(records: list[dict] | None, why: str | None) -> Section:
    s = Section("Provenance", 4)
    if records is None:
        s.note(why or "no store")
        return s
    if not records:
        s.note("the store holds no records yet (Part D)")
        return s
    bad = []
    for r in records:
        missing = [name for name, ok in (
            ("source", SOURCE.match(str(r.get("source") or "")) is not None),
            ("written_at", iso(r.get("written_at"))),
            ("origin", r.get("origin") in ("derived", "ingested")),
            ("confirmed", isinstance(r.get("confirmed"), bool))) if not ok]
        if missing:
            bad.append(f"record {r.get('id')!r}: {', '.join(missing)}")
    s.earned = round(4 * (len(records) - len(bad)) / len(records), 2)
    if bad:
        s.note(f"{len(bad)} of {len(records)} records lack provenance, e.g. " + "; ".join(bad[:3]))
    return s


def check_claim(records: list[dict] | None, store, why: str | None) -> Section:
    s = Section("The issue-body claim", 6)
    if records is None:
        s.note(why or "no store")
        return s
    claims = [r for r in records if CLAIM.search(str(r.get("text") or ""))]
    bad = [f"record {r.get('id')!r}: source {r.get('source')!r}, confirmed {r.get('confirmed')!r}, "
           f"kind {r.get('kind')!r}" for r in claims
           if r.get("source") != f"issue:{CLAIM_ISSUE}" or r.get("confirmed") is not False or r.get("kind") == "semantic"]
    try:
        returned = list(store.active(REPOSITORY) or []) + list(store.active(REPOSITORY, CLAIM_ISSUE) or [])
    except Exception:
        s.note(raised("Store().active"))
        return s
    as_fact = [r for r in returned if r.get("kind") == "semantic" and CLAIM.search(str(r.get("text") or ""))]
    if not bad and not as_fact:
        s.earned = 6
    else:
        s.note("the auto-merge claim from issue 4188's body: " + "; ".join(
            bad[:2] + [f"active() returns it as a semantic fact (record {r.get('id')!r})" for r in as_fact[:1]])
            + f"; want source issue:{CLAIM_ISSUE}, confirmed false, never semantic")
    return s


def check_supersession(records: list[dict] | None, report: dict, why: str | None) -> Section:
    s = Section("Supersession", 6)
    if records is None:
        s.note(why or "no store")
        return s
    rules = [r for r in records if r.get("source") == "user" and RULE.search(str(r.get("text") or ""))]
    active = [r for r in rules if r.get("active") is True]
    inactive = {str(r.get("id")) for r in rules if r.get("active") is False}
    if len(rules) < 2:
        s.note(f"{len(rules)} records of the maintainer's rule on duplicates; the three-session test leaves two "
               "(Part E, task 2)")
        return s
    if len(active) == 1 and str(active[0].get("supersedes")) in inactive:
        s.earned += 4
    else:
        s.note(f"of {len(rules)} records of the maintainer's rule, {len(active)} are active"
               + (f"; the active one supersedes {active[0].get('supersedes')!r}, not an inactive rule" if len(active) == 1
                  else "") + "; want one active record naming the inactive one")
    cited = report.get("contradiction_test")
    if len(active) == 1 and isinstance(cited, list) and [str(i) for i in cited] == [str(active[0].get("id"))]:
        s.earned += 2
    else:
        s.note(f"contradiction_test is {cited!r}; want the third session's retrieval: "
               + (f"[{active[0].get('id')!r}]" if len(active) == 1 else "the one active record"))
    return s


# -- 9. The reopened issue ---------------------------------------------------------------------------

def store_read_first(run: Run) -> dict | None:
    """The run's first store_read line, if it comes before its first search; else None."""
    for r in run.records:
        if r.get("type") == "store_read":
            return r
        if r.get("type") == "tool_call" and role_of(str(r.get("name"))) == "search":
            return None
    return None


def first_search_ok(run: Run) -> bool:
    """A store_read line that returned at least one record comes before the first search."""
    return bool((store_read_first(run) or {}).get("records"))


def check_reopened(runs: list[Run], report: dict) -> Section:
    s = Section("Reopened issue", 6)
    reopened = report.get("reopened") if isinstance(report.get("reopened"), dict) else {}
    by_id = {r.run_id: r for r in runs}
    sets = {}
    for name in ("with_store", "empty_store"):
        part = reopened.get(name) if isinstance(reopened.get(name), dict) else {}
        sets[name] = [str(i) for i in part.get("run_ids") or []]
    every = sets["with_store"] + sets["empty_store"]
    valid = [i for i in every if i in by_id and by_id[i].issue == REOPENED and by_id[i].finished and not by_id[i].die]
    if len(sets["with_store"]) == len(sets["empty_store"]) == RUNS_PER_SET and len(set(every)) == 2 * RUNS_PER_SET \
            and len(valid) == 2 * RUNS_PER_SET:
        s.earned += 2
    else:
        s.note(f"reopened.with_store.run_ids has {len(sets['with_store'])} and empty_store {len(sets['empty_store'])}; "
               f"{len(valid)} of them are finished runs of issue {REOPENED}; want {RUNS_PER_SET} and "
               f"{RUNS_PER_SET}, ten different runs")
    store_runs = [by_id[i] for i in sets["with_store"] if i in by_id]
    if store_runs:
        ok = [r for r in store_runs if first_search_ok(r)]
        s.earned += round(4 * min(len(ok), RUNS_PER_SET) / RUNS_PER_SET, 2)
        late = [r.run_id for r in store_runs if r not in ok]
        if late:
            s.note(f"{len(late)} runs with the store have no store_read line returning a record before their first "
                   f"search, e.g. {late[0]}")
    return s


# -- 10. The boundary that lost it (Part F) -----------------------------------------------------------

def requests_of(run_id: str) -> dict:
    """runs/<run_id>.requests.jsonl, by each line's number: what each model call was sent."""
    path = ROOT / "runs" / f"{run_id}.requests.jsonl"
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out[item.get("n")] = item
    return out


def call_texts(run: Run) -> list[tuple[int, str]]:
    """Each model_call line's place in the trace, with what that call was sent, squeezed."""
    sent = requests_of(run.run_id)
    return [(i, squeeze(request_text(sent[r["request"]]))) for i, r in enumerate(run.records)
            if r.get("type") == "model_call" and r.get("request") in sent]


def drafting_call(run: Run, comment: dict) -> int | None:
    """The trace index of the model call that drafted the posted comment: the latest
    model_call before the comment's tool_call whose call of the comment tool states the
    posted label and file; failing that, the latest that called the comment tool."""
    posted = parse_triage_comment(comment.get("body") or "")
    at = next((i for i, r in enumerate(run.records)
               if r.get("type") == "tool_call" and role_of(str(r.get("name"))) == "comment"), None)
    if at is None:
        return None
    drafts = []
    for i, r in enumerate(run.records[:at]):
        if r.get("type") != "model_call":
            continue
        for c in r.get("tool_calls") or []:
            if role_of(str(c.get("name"))) == "comment":
                bodies = [v for v in (c.get("input") or {}).values() if isinstance(v, str)]
                drafts.append((i, any(parse_triage_comment(b) == posted for b in bodies)))
    exact = [i for i, same in drafts if same]
    return exact[-1] if exact else (drafts[-1][0] if drafts else None)


def shows(comment: dict, effect: dict) -> bool:
    """Whether the comment states what the fact would make it state."""
    label, file = parse_triage_comment(comment.get("body") or "")
    return (("label" not in effect or label == str(effect["label"]).strip().lower())
            and ("file" not in effect or file == normalize_path(str(effect["file"]))))


def part_f_run(rid, by_id: dict, writes: Writes, *, comment: bool = True) -> tuple[dict | None, str | None]:
    """One run Part F names, as the checker reads it, or why it cannot be read."""
    run = by_id.get(str(rid))
    if run is None:
        return None, f"{rid!r} is not a run of this assignment's planned way on your model in runs/"
    if run.issue not in RECORDED_ISSUES:
        return None, f"{rid} is a run of issue {run.issue}; Part F's runs are on 4191 or 4192"
    if run.die or run.resume_at is not None or not run.finished:
        return None, f"{rid} is not a finished, uncrashed run"
    texts = call_texts(run)
    if not texts:
        return None, f"{rid} has no request record: runs/{rid}.requests.jsonl, which the harness writes on 4191 and 4192"
    view = {"run": run, "texts": texts}
    if comment:
        posted = writes.on_issue(run.run_id, run.issue)
        if len(posted) != 1:
            return None, f"{rid} left {len(posted)} comments on {run.issue}; one is read"
        at = drafting_call(run, posted[0])
        drafted = next((text for i, text in texts if i == at), None)
        if drafted is None:
            return None, f"{rid}: no model call with a line in the request record drafted its comment"
        view.update(comment=posted[0], at=at, drafted=drafted)
    return view, None


def from_an_end(view: dict, fact: str) -> int:
    """How deep the fact sits in what the drafting call was sent: the characters between
    it and the nearer end, the start or the finish."""
    text = view["drafted"]
    return min(text.find(fact), len(text) - (text.rfind(fact) + len(fact)))


def first_compaction(view: dict) -> int | None:
    return next((i for i, r in enumerate(view["run"].records) if r.get("type") == "compaction"), None)


def judge_case(case: str, entry: dict, by_id: dict, writes: Writes, records: list[dict] | None) -> dict[str, str | None]:
    """Part F, one case: why its lost run and its fixed run fail, or None for a pass."""
    fact, effect = squeeze(entry.get("fact")), entry.get("effect")
    lost, why_lost = part_f_run(entry.get("lost"), by_id, writes)
    fixed, why_fixed = part_f_run(entry.get("fixed"), by_id, writes)
    out = {"lost": why_lost, "fixed": why_fixed}
    for role, view in (("lost", lost), ("fixed", fixed)):
        if view is None:
            continue
        used, held = shows(view["comment"], effect), fact in view["drafted"]
        if role == "lost" and used:
            out[role] = f"its comment states {effect}: the fact was not lost"
        elif role == "fixed" and not used:
            out[role] = f"its comment does not state {effect}: the fix did not bring the fact back"
        elif case == "attention" and not held:
            out[role] = "the call that drafted its comment was not sent the fact: for attention, it is in the window"
        elif case == "compaction":
            c = first_compaction(view)
            if c is None or c > view["at"]:
                out[role] = "no compaction line before the call that drafted its comment"
            elif not any(fact in text for i, text in view["texts"] if i < c):
                out[role] = "no call before its first compaction was sent the fact"
            elif role == "lost" and held:
                out[role] = "the call that drafted its comment was still sent the fact after the compaction"
            elif role == "fixed" and not held:
                out[role] = "the call that drafted its comment was not sent the fact"
        elif case == "session":
            if role == "lost" and any(fact in text for _, text in view["texts"]):
                out[role] = "a call of this run was sent the fact: in the session case, nothing carries it over"
            elif role == "fixed" and not held:
                out[role] = "the call that drafted its comment was not sent the fact"
    if case == "attention" and out["fixed"] is None:
        if lost is None or fact not in lost["drafted"]:
            out["fixed"] = "there is no lost run, sent the fact, to compare it with"
        elif from_an_end(fixed, fact) >= from_an_end(lost, fact):
            out["fixed"] = (f"the fact sits {from_an_end(fixed, fact):,} characters from the nearer end of what the "
                            f"call that drafted its comment was sent, and {from_an_end(lost, fact):,} in the lost run's: "
                            "want fewer, from a shorter context or a more prominent place")
    if case == "session":
        stated, why = part_f_run(entry.get("stated"), by_id, writes, comment=False)
        if stated is None:
            why = f"stated: {why}"
        elif not any(fact in text for _, text in stated["texts"]):
            why = "stated: no call of the stated run was sent the fact"
        for role, view in (("lost", lost), ("fixed", fixed)):
            if out[role] is None and (why or view["run"].order <= stated["run"].order):
                out[role] = why or f"it started before the stated run, {entry.get('stated')}"
        if out["fixed"] is None:
            kept = [r for r in records or [] if r.get("active") is True and fact in squeeze(r.get("text"))]
            if not first_search_ok(fixed["run"]):
                out["fixed"] = "no store_read line returning a record before its first search"
            elif not kept:
                out["fixed"] = "no active record in your store holds the fact, word for word"
    return out


def check_forgetting(runs: list[Run], report: dict, writes: Writes, records: list[dict] | None) -> Section:
    s = Section("The boundary that lost it", 12)
    part = report.get("forgetting") if isinstance(report.get("forgetting"), dict) else {}
    by_id = {r.run_id: r for r in runs}
    for case in CASES:
        entry = part.get(case) if isinstance(part.get(case), dict) else {}
        effect = entry.get("effect")
        if not entry:
            s.note(f"{case}: reports/LAB_04.json has no forgetting.{case} (Part F)")
            continue
        if not squeeze(entry.get("fact")) or not isinstance(effect, dict) or not ({"label", "file"} & set(effect)):
            s.note(f"{case}: forgetting.{case} needs the fact, word for word, and its effect: a label, a file or both")
            continue
        verdict = judge_case(case, entry, by_id, writes, records)
        for role in ("lost", "fixed"):
            if verdict[role] is None:
                s.earned += 2
            else:
                s.note(f"{case}, {role} ({entry.get(role)}): {verdict[role]}")
    return s


# -- for staff -----------------------------------------------------------------------------------------

def answers() -> dict:
    data = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())
    return {int(k): v for part in ("eval", "dev") for k, v in data[part].items()}


def passes(run_id: str, issue: int, writes: Writes, key: dict) -> bool:
    comments = writes.on_issue(run_id, issue)
    if len(comments) != 1:
        return False
    label, file = parse_triage_comment(comments[0]["body"])
    return label == key[issue]["label"] and file == normalize_path(key[issue]["file"])


def staff_notes(runs: list[Run], report: dict, writes: Writes) -> list[str]:
    notes = []
    by_id = {r.run_id: r for r in runs}
    for name in ("matrix_derived", "matrix_uuid"):
        for entry in report.get(name) or []:
            if not isinstance(entry, dict):
                continue
            rid = str(entry.get("run_id"))
            truth = (len(writes.on_issue(rid, MATRIX_ISSUE)), len(writes.open_prs(rid, BRANCH)))
            if (entry.get("comments"), entry.get("open_prs")) != truth:
                notes.append(f"{name} {rid}: comments and open_prs {entry.get('comments')}, {entry.get('open_prs')}; "
                             f"the tracker holds {truth[0]}, {truth[1]}")
            run = by_id.get(rid)
            if run and run.die and (run.die.get("when"), run.die.get("step")) != (entry.get("when"), entry.get("step")):
                notes.append(f"{name} {rid}: listed as {entry.get('when')} step {entry.get('step')}; its run_start "
                             f"says {run.die.get('when')} step {run.die.get('step')}")
    key = answers()
    reopened = report.get("reopened") if isinstance(report.get("reopened"), dict) else {}
    for name, part in reopened.items():
        if not isinstance(part, dict):
            continue
        ids = [str(i) for i in part.get("run_ids") or [] if str(i) in by_id]
        if not ids:
            continue
        got = sum(passes(i, REOPENED, writes, key) for i in ids)
        calls = sum(len(by_id[i].lines("tool_call")) for i in ids) / len(ids)
        tokens = sum((by_id[i].lines("run_end")[-1].get("totals") or {}).get("total_tokens", 0)
                     for i in ids if by_id[i].lines("run_end")) / len(ids)
        if part.get("passes") != got:
            notes.append(f"reopened.{name}.passes is {part.get('passes')}; by the tracker {got} of {len(ids)}")
        if part.get("mean_tool_calls") is not None and abs(float(part["mean_tool_calls"]) - calls) > 0.05:
            notes.append(f"reopened.{name}.mean_tool_calls is {part['mean_tool_calls']}; the traces give {calls:.2f}")
        if part.get("mean_tokens") is not None and abs(float(part["mean_tokens"]) - tokens) > max(1.0, tokens * 0.01):
            notes.append(f"reopened.{name}.mean_tokens is {part['mean_tokens']}; the traces give {tokens:.0f}")
    empty = (reopened.get("empty_store") or {}).get("run_ids") if isinstance(reopened.get("empty_store"), dict) else []
    filled = [i for i in empty or [] if str(i) in by_id and (store_read_first(by_id[str(i)]) or {}).get("records")]
    if filled:
        notes.append(f"reopened.empty_store: {len(filled)} runs whose store read returned records, e.g. {filled[0]}")
    if not isinstance(report.get("checkpoint_bytes"), dict) or not report["checkpoint_bytes"].get("structured"):
        notes.append("reports/LAB_04.json has no checkpoint_bytes.structured (Part E, task 3)")
    if not report.get("plan_marks") or report.get("durability") not in ("sync", "async", "exit"):
        notes.append("reports/LAB_04.json has no plan_marks or no durability (Part A)")
    return notes


REF = re.compile(r"`([\w./-]+\.\w+):(\d+)`")


def architecture_notes() -> list[str]:
    path = ROOT / "ARCHITECTURE.md"
    if not path.exists():
        return ["ARCHITECTURE.md is missing"]
    notes = []
    for file, line in REF.findall(path.read_text()):
        target = ROOT / file
        if file.startswith("prompts/"):
            notes.append(f"ARCHITECTURE.md cites `{file}:{line}`, a prompt: a layer held only by a prompt is EMPTY")
        elif not target.is_file():
            notes.append(f"ARCHITECTURE.md cites `{file}:{line}`: no such file")
        elif not 1 <= int(line) <= len(target.read_text().splitlines()):
            notes.append(f"ARCHITECTURE.md cites `{file}:{line}`: the file has no line {line}")
    return notes


def integrity_flags(report: dict, runs: list[Run] | None = None) -> list[str]:
    flags = []
    others = sorted({r.start.get("backend") for r in runs or [] if r.start.get("backend") not in REAL_BACKENDS})
    if others:
        flags.append(f"runs scored here came from a backend that is not a vendor's: {', '.join(map(str, others))}")
    key = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"]
    paths = {a["file"] for a in key.values() if a["file"] != "none"}
    for d in ("prompts", "ways", "agent", "tools", "state"):
        for place in sorted((ROOT / d).rglob("*")):
            if not place.is_file() or place.suffix not in ((".py",) if d == "state" else (".py", ".md", ".json", ".yaml")):
                continue
            try:
                text = place.read_text()
            except UnicodeDecodeError:
                continue
            rel = place.relative_to(ROOT).as_posix()
            for path in sorted(paths):
                if path in text:
                    flags.append(f"`{rel}` contains the evaluation answer `{path}`")
            if "answers.yaml" in text:
                flags.append(f"`{rel}` reads the answer file; only eval/ should")
            if d != "prompts" and "attempts" in text and ("table(" in text or "FROM attempts" in text):
                flags.append(f"`{rel}` reads the tracker's attempts log, which is the tracker's, not your harness's")
    reopened = report.get("reopened") if isinstance(report.get("reopened"), dict) else {}
    both = set(str(i) for i in ((reopened.get("with_store") or {}).get("run_ids") or [])) & \
        set(str(i) for i in ((reopened.get("empty_store") or {}).get("run_ids") or []))
    if both:
        flags.append(f"runs listed in both reopened sets: {sorted(both)[:3]}")
    for rel, wanted in HARNESS_SHA.items():
        if wanted and sha(ROOT / rel) != wanted:
            flags.append(f"`{rel}` differs from the course's copy: the kills, the resumes and Part F's request "
                         "record depend on it")
    return flags


def main() -> int:
    report_path = ROOT / "reports" / "LAB_04.json"
    try:
        report = json.loads(report_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"reports/LAB_04.json could not be read ({exc}); checking what can be checked without it.\n")
        report = {}
    if not isinstance(report, dict):
        report = {}
    runs, load_notes, scripted = load_runs()
    writes = Writes()
    cps, cp_why = checkpoints_of(runs)
    records, store, store_why = store_records()
    checks = [
        (lambda: check_contents(runs, cps, cp_why), "Checkpoint contents", 6),
        (lambda: check_sync(runs), "Sync before writes", 8),
        (lambda: check_resume(runs), "Resume, not restart", 8),
        (lambda: check_derived(runs, report, writes, cps, cp_why), "Crash matrix, derived keys", 20),
        (lambda: check_uuid(runs, report, writes), "Crash matrix, random keys", 6),
        (lambda: check_provenance(records, store_why), "Provenance", 4),
        (lambda: check_claim(records, store, store_why), "The issue-body claim", 6),
        (lambda: check_supersession(records, report, store_why), "Supersession", 6),
        (lambda: check_reopened(runs, report), "Reopened issue", 6),
        (lambda: check_forgetting(runs, report, writes, records), "The boundary that lost it", 12),
    ]
    sections = []
    for check, name, pts in checks:
        try:
            sections.append(check())
        except Exception:
            sections.append(Section(name, pts, notes=[raised("this check")]))
    sections.append(Section("Report", 18, manual=True, notes=["read by staff from reports/LAB_04.md"]))

    backends = sorted({r.start.get("backend") for r in runs})
    killed = sum(1 for r in runs if r.die)
    print(f"Assignment 4 check · runs read from runs/ · backends seen: {', '.join(backends) or 'none'}")
    print(f"  {len(runs)} runs of the planned way on your model, {killed} of them killed; tracker databases read: "
          f"{len(writes.files)} (the live one and its archives)")
    if scripted:
        print(f"  {scripted} runs on a scripted model are left out: they test your code, and score nothing")
    if any(b not in REAL_BACKENDS for b in backends):
        print("  note: runs from a scripted or simulated backend are not a measurement of a model")
    for note in load_notes[:5]:
        print(f"  note: {note}")
    print()
    auto_earned = auto_possible = 0.0
    for sec in sections:
        score = "staff" if sec.manual else f"{round(sec.earned, 2):>5g} / {sec.possible:g}"
        print(f"{sec.name:<28} {score}")
        for note in sec.notes:
            for i, line in enumerate(note.splitlines()):
                print(f"{'    - ' if i == 0 else '      '}{line}")
        if not sec.manual:
            auto_earned += sec.earned
            auto_possible += sec.possible
    print(f"\nAutomated: {round(auto_earned, 2):g} / {auto_possible:g}   (plus up to 18 from staff for the report)")
    for note in staff_notes(runs, report, writes) + architecture_notes():
        print(f"  for staff: {note}")
    flags = integrity_flags(report, runs)
    print("\nIntegrity flags (no points; staff review): " + ("none" if not flags else ""))
    for flag in flags:
        print(f"    - Integrity flag: {flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
