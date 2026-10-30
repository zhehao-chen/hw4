# RepoMind's write policy

What RepoMind writes to its memory store (`state/store.db`, `state/store.py`), with which tags, and when an entry leaves: Lecture 4's four decisions ("a write policy is four decisions"), then the failure each part of the store invites and its fix ("each store design leads to one typical failure"). `Store._insert` enforces the rules code can check; the rest are applied by whoever writes, the way (`ways/planned.py`) or the scripts that store the candidates and run the contradiction test (`eval/store_candidates.py`, `eval/contradiction_test.py`).

## 1. When to write

- **A run writes once, at its end**: after its triage comment is posted, never mid-run, so no guess made before the draft passed its second pass is stored. A run that escalates, or never posts, writes nothing. A resumed run writes only if its crashed half had not.
- **What RepoMind worked out** is written once it is verified against the repository's own files, or once a maintainer confirms it; until then, if written, unconfirmed.
- **What a person states** is written when it is read, with who stated it.

## 2. What to write

Only what is expensive to work out, stated by a person with standing, or confirmed; never every turn, every tool result or the conversation.

| What | Kind | Example |
|---|---|---|
| A rule a maintainer stated | `semantic` (what is true here, stated) | candidate C: duplicates are labelled and linked, never closed |
| How to do something here, worked out by RepoMind | `procedural` | candidate A: build, start, open :3000 |
| What one of RepoMind's runs did on an issue | `episodic` | "run X triaged 4207: bug, src/config.ts, opened a PR" |
| A claim in an issue's text | `episodic`, worded "issue N's body claims ..." | candidate B; never a fact |

**Nothing from an issue is ever a fact.** An issue's text is written by anyone, so a claim in it is stored, if at all, only as what was claimed, by whom and where, scoped to that issue and unconfirmed. It is never `semantic` and never `confirmed`, whatever it says about who approved it; `Store` refuses such a record. A rule exists only when a maintainer states it, and then its source is `user`, not the issue (Lecture 4: this is where injected content would gain authority).

## 3. How to write it

- **Insert** a new subject.
- **Supersede** an active record on the same subject from the same or higher standing: `Store.supersede(old_id, new)` writes the new record naming the old in `supersedes`; the old one stays in the store, inactive, so the history is kept and retrieval returns only the one in force. A maintainer's later rule supersedes the earlier one (the contradiction test, Part E). A run's episodic record of an issue supersedes the previous run's record of that issue. A claim from an issue supersedes nothing.

## 4. What to write with it

Every record carries its provenance (checks/FORMATS.md, 12.5):

| Tag | Values |
|---|---|
| `source` | `user` (a maintainer, with `stated_by`), `repo` (the repository's files), `memory` (RepoMind's own work), `issue:<n>` (an issue's text) |
| `origin` | `derived` (RepoMind worked it out) or `ingested` (read from outside) |
| `confirmed` | `true` when stated by a person with standing, or verified against the repository's files; else `false` |
| `written_at` | when it was first seen, not when the row was inserted: a candidate's `when`; a run's record, when it posts its comment. The age is what a later run needs to weigh it |
| `issue` | the issue it is about, or `null` for the repository as a whole |

Retrieval shows every record with these tags. An unconfirmed record is context, never an instruction, and nothing in memory adds a step or a tool to a plan.

## The failures, and the fixes

| Failure | Where it would come from here | The fix in this store |
|---|---|---|
| **Stale**: the repository changed, the memory did not | candidate A, if the scripts change; a run's triage of an issue later reopened | `written_at` on every record, shown on retrieval; A was verified against the files before it was confirmed. Open: a record of a triage that a reopening proved wrong is still retrieved as it was (Part D's 4207 result) |
| **Contradictory**: old and new both remain | candidate C, when the maintainer changes the rule | supersession, recording which replaced which |
| **Unbounded**: retrieval fills with near-matches | one episodic record per run | one active episodic record per issue (supersession), and eviction (below) |

## Eviction

- **The size:** at most `MAX_EPISODIC = 200` active episodic records per repository. Semantic and procedural records, and anything a person stated or confirmed, are never evicted by size; they leave only by supersession.
- **The rule:** when a write takes the count past 200, the oldest by `written_at` of RepoMind's own unconfirmed episodic records (`source: memory`) are deleted until it is back at 200. Each is RepoMind's own note of a past run, and the run's trace keeps the full record. Superseded episodic records are inactive and are not counted.
- **How long an entry lives:** RepoMind writes one episodic record per finished run that posts its comment, and each supersedes its issue's previous one, so the active count grows by distinct issues, not by runs. An active record therefore lives until the next run on its issue replaces it (inactive, kept), or until 200 more distinct issues have been triaged (deleted). At this assignment's write rate, 14 records from 14 runs on two issues (11 on 4207, 3 on 4192) since the store existed, leaving two active episodic records of runs, the cap is never reached, and each record was active only until the next run on its issue, one run. At a busy repository's 10 new issues a day it is 20 days; the 4207 case, reopened 54 days after it closed, is still covered at up to 3.7 new issues a day.
