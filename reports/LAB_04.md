# Assignment 4 · Kill it and resume: state, keys and a memory with provenance

Model: OpenAI, gpt-4o-mini (served as gpt-4o-mini-2024-07-18), the same for every run.

## Part A · Mark the plan, place the checkpoints

The plan of issue 4201 (scripted run `planned-4201-s01-9344fc`, and the uncrashed run on the model, `planned-4201-s01-aa72c7`): read the issue, search, read a file, open the PR, post the comment.

| Step | Tool | Kind | Checkpoint |
|---|---|---|---|
| 1 | `issues_read` (read the issue) | read | after |
| 2 | `code_search` (search) | read | after |
| 3 | `code_read_file` (read a file) | read | after |
| 4 | `pulls_open` (open the draft PR) | keyed write | before |
| 5 | `issues_comment` (post the triage comment) | keyed write | before |

- **Where.** A sync checkpoint immediately before each write, holding the write's arguments (`findings.pending_write`) and, before the first write, the checked comment draft (`findings.draft`, `label`, `file`). The keys are hashes of the run, the plan step and the arguments, and those arguments are written by the model, so they have to be on disk before the write runs: a resume replays them, never a fresh fill. A checkpoint after each read too, because in this way every read but the first is preceded by a model call that fills its arguments (the search query, the file path), and the one after step 1 also keeps the validated plan, so a resume never calls the planner again. Each read's checkpoint names the read it comes after as `step`, and the next step as `current_step`. The replay window therefore never holds more than the step that was running at the crash.
- **Durability mode: sync.** The run has two irreversible steps. In exit mode a crash loses every checkpoint; in async mode the save before a write may still be in flight when the write commits, so a crash in that gap resumes with no record of the arguments, and a fresh fill makes a new key. Sync costs one SQLite commit (an fsync) per step, a few milliseconds against seconds per model call. `state/checkpointer.py` implements all three modes; the way uses sync (`DURABILITY` in `ways/planned.py`).
- **The weaker write is the comment.** Both carry a derived key, but if the key were lost or changed (a fresh random key, or new arguments from a fresh fill), the PR would still be stopped by Assignment 3's check before every attempt, which looks for an open PR from `repomind/issue-<n>` in this run by its branch. The comment has nothing but its key: the check before a comment looks it up by key, so a different key finds nothing and the comment posts again. A comment, once read, also cannot be taken back, which is why it goes last.

## Part B · Kill it at every step

**The hand walk, written before the matrix.** The crash I expect to be worst: `--die-during-step 5`, the comment killed after the tracker committed it and before the reply came back.

- Its last checkpoint: the sync checkpoint for step 5, saved immediately before the comment's call. It holds the plan, steps 1 to 4 `done`, step 5 `running`, `completed_calls` for steps 1 to 4 (the PR with its key and result), `findings` with label `bug`, the file, the draft and `pending_write` (the comment's exact arguments), and `current_step: 5`.
- The steps between it and the crash, and the step running at the crash: none between; the running step is step 5 itself, the one most people leave out. The process never learned whether it happened, and it did: the tracker committed it.
- For each: step 5 has a side effect (a public comment). Placement cannot close it; the resume replays it through the registry with the saved arguments, so the derived key is the same, and the registry's check before the attempt asks the tracker by that key, finds the comment, and returns it as already there. The key closes it. Steps 1 to 4 are skipped from `completed_calls` (recorded results); the PR is also covered by its key and by the branch check. I expect one comment and one PR. With `KEY_MODE=uuid` I expect this case, and `--die-after-step 5`, to leave two comments, and every other case to leave one.
- `--die-during-step 4` / `--die-after-step 4` are the same shape for the PR: it committed, the process never learned, and the replay finds it by key (and by branch). The comment has not been posted yet, so it posts once.
- Crashes at steps 1 to 3 have no write in the replay window. After step 1 (killed before its checkpoint) the run starts over: it re-plans and reads the issue again, which costs tokens but writes nothing; it may decide differently from the uncrashed run, which is allowed.

**The matrix, derived keys.** Uncrashed run: `planned-4201-s01-aa72c7` (label bug, `src/notifications/templates.ts`, five steps).

| Step | When | run_id | Comments | Open PRs | Matches its findings |
|---|---|---|---|---|---|
| 1 | after | `planned-4201-s01-8020b8` | 1 | 1 | yes (bug, `src/api/auth.ts`) |
| 1 | during | `planned-4201-s01-196b1f` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |
| 2 | after | `planned-4201-s01-129b15` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |
| 2 | during | `planned-4201-s01-dee9cb` | 1 | 1 | yes (bug, `src/api/auth.ts`) |
| 3 | after | `planned-4201-s01-2e1cb0` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |
| 3 | during | `planned-4201-s01-c8b9d5` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |
| 4 | after | `planned-4201-s01-47ce2b` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |
| 4 | during | `planned-4201-s01-7bd742` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |
| 5 | after | `planned-4201-s01-74d278` | 1 | 1 | yes (bug, `src/api/auth.ts`) |
| 5 | during | `planned-4201-s01-06e0d5` | 1 | 1 | yes (bug, `src/notifications/templates.ts`) |

Counted from the tracker by `run_id` (`Tracker().comments(run_id, 4201)` and `Tracker().prs(run_id, branch="repomind/issue-4201")`) with `eval/crash_matrix.py`, and the same by `make check-04` (20 / 20). Every crashed run's plan had the same five steps as the uncrashed run; two (`8020b8`, `196b1f`) revised their plan once after the first search, which kept the five steps. Three runs name `src/api/auth.ts`, not the uncrashed run's file: each decided its file in a fresh model call (the crashes of `8020b8` and `dee9cb` came before the draft was saved; `74d278`'s draft was made before its crash by its own fill), and each one's comment and PR match its own last checkpointed findings. No case left a second comment or a second PR.

## Part C · Break it on purpose

After `make reset` (Part B's tracker is archived as `tracker/archive/tracker-20261027-212611.db`), every case again, with `KEY_MODE=uuid` on each crashed run; each resume kept the run's own switches, so its half ran with random keys too. Counted from the tracker by `run_id`.

| Step | When | run_id | Comments | Comment IDs | Open PRs |
|---|---|---|---|---|---|
| 1 | after | `planned-4201-s01-abe8c1` | 1 | 1 | 1 |
| 1 | during | `planned-4201-s01-281d2e` | 1 | 2 | 1 |
| 2 | after | `planned-4201-s01-bbd19f` | 1 | 3 | 1 |
| 2 | during | `planned-4201-s01-a8dcb6` | 1 | 4 | 1 |
| 3 | after | `planned-4201-s01-c2212c` | 1 | 5 | 1 |
| 3 | during | `planned-4201-s01-0a7d23` | 1 | 6 | 1 |
| 4 | after | `planned-4201-s01-c0a6af` | 1 | 7 | 1 |
| 4 | during | `planned-4201-s01-93efd6` | 1 | 8 | 1 |
| 5 | after | `planned-4201-s01-4f30fe` | **2** | **9, 10** | 0 |
| 5 | during | `planned-4201-s01-59bdfb` | **2** | **11, 12** | 0 |

Only N = 5 produced a second comment, both ways, as the hand walk predicted. In each, the trace shows the comment's `tool_call` before the crash (or, for `during`, the tracker's row with no `tool_call`), then the `resume` line, a `restored` line with steps 1 to 4 finished, one sync checkpoint for step 5, and one more `issues_comment` call with the same arguments, which the tracker stored as a second comment (IDs 10 and 12). No case left a second PR: at N = 4 the replayed PR carried a fresh key, and the registry's check before the attempt still found the open PR by its branch, `repomind/issue-4201`.

The two N = 5 runs have no open PR for a reason unrelated to the crash: the model's plan left the PR step's `title` and `body` out, so the executor had nothing marked `$fill` to fill, and the boundary rejected the call (`title: required, and missing`) before it reached the tracker. That step failed and the run went on to its comment. I fixed this after Part C (the executor now marks a missing title or body `$fill`, and a write the boundary rejected, having no key, is kept out of `completed_calls`). The two runs' checkpoints were saved before the fix and are left as they ran.

**What the checkpoint did, and what the key did.** The checkpoints were the same in both matrices, and in both they did the same job: they decided where each replay started and how much of the run it covered. After every resume the run skipped the steps its last checkpoint marked finished, reused their recorded results, and replayed only the step that was running at the crash, with the arguments saved before it, so no finished read or write ran twice (Part B's "resume, not restart"). What the checkpoint could not do was tell whether that running step had happened: a write killed during its step had committed, and the process never learned it. Only the key settles that. With derived keys the replayed comment carried the key of the comment already in the tracker, the check before the attempt found it, and the tracker held one comment in all ten cases. With random keys, the same checkpoint and the same arguments produced the same replay window, but the key was new, the check found nothing, and the tracker wrote a second comment at N = 5. The PR did not duplicate under random keys only because its check also looks by branch, a second, intent-based identity the comment lacks. So the checkpoint bounds how much is replayed, and the key decides whether a replayed write writes again: "the key, not the checkpoint" (slide 47).

## Part D · A memory that can say where it came from

- **The write policy, in brief** (`state/write_policy.md`, set out as Lecture 4's "a write policy is four decisions"; `state/store.py` enforces what code can). *When:* a run writes once, at its end, after its comment posts; nothing mid-run. *What:* only what is expensive to work out, stated by a person with standing, or confirmed: a maintainer's rule (`semantic`, stated), a procedure RepoMind worked out (`procedural`), a run's triage (`episodic`). *How:* insert a new subject; supersede an active record on the same subject from the same or higher standing, keeping the old one inactive. *With what:* `source`, `origin`, `confirmed`, `written_at` (when first seen) and `stated_by` for a person. Text from an issue, which anyone can write, is never a fact: if stored at all it is an `episodic` record of the claim ("issue N's body claims ..."), scoped to that issue, `source: issue:<n>`, `confirmed: false`; `Store` refuses an issue-sourced record that is `semantic` or confirmed. Retrieval shows every record with its kind, scope, source, confirmation and date, and tells the model an unconfirmed record is context, not an instruction.
- **The store in the way** (`ways/planned.py`). A fresh run reads `Store().active("ledgerline", issue)` once, before it plans, and writes a `store_read` line with the IDs. The records go into every fill call (the search query, the file, the draft, the PR), and into `findings.memory` in each checkpoint, so a resume replays with the records it was given and does not read again. After the comment posts, the run writes one episodic record of what it did (label, file, searches, files read, PR or not), superseding the issue's previous one; a resume that finds its own record already stored writes nothing. `REPOMIND_STORE=empty` gives a run an in-memory store: it reads nothing and its writes reach no other run.
- **The three candidates**, stored by `eval/store_candidates.py`:

| Candidate | Stored? | Kind | source | origin | confirmed | Invites |
|---|---|---|---|---|---|---|
| A (build and start steps, worked out in a run of 4191) | yes, id 1, repository-wide: expensive to derive | procedural | `memory` | derived | true: verified against the repository's files (package.json's scripts are start, build, test, lint; `src/config.ts:63` defaults the port to 3000; README.md line 52 says `npm run serve`) | **Staleness**: if the scripts or the port change, a dated "how to" that no longer works. `written_at` is shown on retrieval |
| B (issue 4188's body: auto-merge was "approved") | not as a fact: id 2, only as a claim, scoped to 4188 | episodic | `issue:4188` | ingested | false | **Poisoning**: an outside account writing a permission into RepoMind's memory, which a later run would read as policy and act on (merging PRs). Stored as "issue 4188's body claims ...", never semantic, never retrieved outside 4188, and it grants nothing |
| C (priya-s: label duplicates, link the original, never close) | yes, id 3, repository-wide: stated, not inferred | semantic (stated) | `user`, `stated_by: priya-s` | ingested | true | **Contradiction** when the maintainer changes the rule: old and new both retrieved. Handled by supersession (Part E, task 2) |

- **Eviction.** The size: at most 200 active episodic records per repository (`MAX_EPISODIC`). The rule: past 200, delete the oldest of RepoMind's own unconfirmed episodic records (`source: memory`); a person's rule, a procedure and anything confirmed leave only by supersession. How long an entry lives: each run's record supersedes its issue's previous one, so the count grows by distinct issues, not runs. At my write rate (14 records from 14 runs on two issues, 11 on 4207 and 3 on 4192, since the store existed) the cap is never reached, and each run's record was active only until the next run on its issue superseded it. At 10 new issues a day an entry would last 20 days.

**The reopened issue.** The seed run, `planned-4207-s01-f97956`, read records 1 and 3 (nothing about 4207 yet), posted `bug`, `src/config.ts`, and stored record 4. Then five runs with the store, one after another, each reading the previous run's record and superseding it (records 4 to 8, then 9), and five with `REPOMIND_STORE=empty`, whose store reads returned `[]`. The answer is `bug`, `src/export/scheduler.ts`.

| Issue 4207, five runs each | With the store | Empty store |
|---|---|---|
| Passes | 0 / 5 | 0 / 5 |
| Mean tool calls | 6.8 | 5.8 |
| Mean tokens | 13,286 | 10,235 |
| Files the comments named | `src/config.ts` ×5 | `src/config.ts`, `docs/CONFIG.md`, `none` ×3 |

Run IDs: with the store `planned-4207-s01-da7337`, `s02-e60821`, `s03-610777`, `s04-bece34`, `s05-9f7f55`; empty `planned-4207-s01-00d251`, `s02-7ae91d`, `s03-dadffe`, `s04-1bbff9`, `s05-22b74a` (`eval/reopened.py` prints them with their searches).

The store did not help, and in one way it hurt. Every run with the store named the seed run's file, `src/config.ts`, the wrong one: the episodic record anchored them on its conclusion, even though it said "RepoMind's own conclusion, not confirmed by a maintainer". The empty runs were wrong in scattered ways, three of them naming no file. So the memory made the runs consistent, not correct, and carried one wrong triage forward five times. The first search, `weekly scheduled export`, was the same in all ten runs and found no source file, so the checkpoint revised the search (twice in nine of the ten runs), with queries such as `bug fix` that the memory did not shape. The tool calls differ (6.8 against 5.8) because four store runs and two empty runs made a third search, and three empty runs, naming no file, skipped the PR. The tokens differ for two reasons: the rendered records add about 300 tokens to each fill call (about 1,200 a run), and three empty runs named no file, so they skipped the PR and its fill (about 8,800 tokens each, against 11,600 and 13,300 for the two that opened one). Two things follow for the policy. The issue was reopened, which is itself evidence that the last triage did not settle it; a record of an earlier triage of a reopened issue should be shown as "this conclusion did not hold", or not retrieved at all. And what the planned way lacks on 4207 is a search for the schedule code (`schedule`, `weekly`), which no memory written by these runs could supply: the store can only return what an earlier run knew.

## Part E · Answer from your own runs

1. **My prediction against the matrix.** The hand walk (Part B) predicted one comment and one PR in every derived-key case, and with `KEY_MODE=uuid` two comments at step 5, after and during, and one everywhere else. Both matrices came out that way: 10 of 10 derived cases with one comment and one PR, and under random keys exactly `4f30fe` and `59bdfb` (step 5) with two comments, IDs 9 and 10, 11 and 12. I also predicted, correctly, that random keys would not duplicate the PR at step 4, since the check before the attempt also finds an open PR by its branch. What I did not predict: the two step-5 uuid runs had no PR at all, because the model's plan left the PR's title and body out and the boundary rejected the call. That was a bug in the executor (fixed after Part C), not a crash effect, and it is why those two runs' checkpoints still fail the "Checkpoint contents" row: their `completed_calls` hold the rejected PR call with no key, saved before the fix. I also expected the crashes at steps 1 to 3 to be the cheap ones, and they were, but three cases (`8020b8`, `dee9cb`, `74d278`) named a different file from the uncrashed run: each chose its file in its own model call, two of them after the crash, and the model does not choose the same way every time. Each still matched its own last checkpoint.
2. **The contradiction test** (`eval/contradiction_test.py`, three sessions, each its own process, on the real store). Session 1: the maintainer's rule on duplicates (candidate C) is record 3, `source: user`, `stated_by: priya-s`, confirmed. Session 2: the same maintainer states, on 2026-10-28, that RepoMind should now close duplicates itself once the link is posted. The session looks up the active `user` rule on the subject (`Store.search("ledgerline", "duplicate")`), finds record 3, and calls `supersede(3, ...)`: record 10, naming 3 in `supersedes`; record 3 stays in the store, inactive. Session 3 retrieves the rule on duplicates and gets **[10]** only. Without supersession it would have got both, "never close them" and "close them yourself", with nothing in the store to say which holds.
3. **What the checkpoint cost**, over **3 runs** on issue 4192 (`2aa362`, `0a0cb7`, `1db603`; a fourth, `615cb8`, escalated before its plan and saved none), by `eval/checkpoint_bytes.py`. Structured, through `state/checkpointer.py`: a mean of **38,132 bytes** a run, 6 or 7 checkpoints of about 5.5 KB each. With the conversation (each checkpoint plus every request the run had sent by then, from its request record, and every response, from its trace; saved to `state/checkpoints_conversation.db`): **207,358 bytes**, 5.4 times as much. The structured checkpoint is mostly `completed_calls` (4.6 KB of the last one's 7.8 KB, the file read alone 2.1 KB), then `findings` (1.7 KB, with the draft and the memory records) and the plan (1.4 KB). The conversation adds the system prompts and tool definitions sent with every call, again and again; none of it is needed to resume, since a resume calls the model afresh from the structured state. And it is not what a resume should replay: replaying a conversation means trusting text the model wrote, where the structured checkpoint holds only checked results. Each checkpoint is a full snapshot, not a delta, so the total grows with the square of the steps; at seven steps that costs little, and it means `last()` alone is enough to resume.
4. **Is what you built durable execution?** No: by Lecture 4 durable execution is checkpoint, journal (call log) and supervisor, and I built the first, most of the second, and none of the third. The lecture's three questions before calling a checkpoint durable, answered from my runs:
   - *Does it notice that the run died?* No. A killed run leaves a trace with no `run_end` and a ledger row; nothing watches for either. Nobody knows until someone looks.
   - *Does it restart the run without a person?* No. Every one of Part B's and C's twenty resumes was `python run.py --resume <run_id>`, typed by me.
   - *Does it stop finished work being done twice?* Yes for tool calls, no for model calls. `completed_calls` acts as a journal of tool calls: a resumed run skipped every finished step and reused its recorded result (the checker's "Resume, not restart", 8 / 8), and the call in flight was settled by its key (one comment and one PR in all ten derived cases). But model calls are not journaled: a crash before a checkpoint made the resumed run call the model again, and three Part B runs (`8020b8`, `dee9cb`, `74d278`) chose a different file from the uncrashed run.

   One yes out of three: in the lecture's words, a recovery aid, not a guarantee. It is still enough for what the matrix measured, because the writes come last, each behind a sync checkpoint, and each carries a key; what it does not give is a half-done run that finishes on its own.
5. **Which abstraction?** The lecture's four questions ("answer all four: each adds one piece to the design"), answered for RepoMind:
   - *Do you know the steps and their order in advance?* Yes: the planned way validates a plan before anything runs, and the order (read, search, read, PR, comment) is fixed by the schema check. **A graph.**
   - *Do runs outlive a single process?* Yes: Part B killed twenty runs and resumed them in new processes. **Checkpoints on disk**, which `state/checkpointer.py` already saves, sync.
   - *Do steps have irreversible side effects?* Yes: a public comment, and a PR. **A key on every write** (Part C showed what one random key does: a second comment). Durable execution only if a half-done run must finish on its own; for a triage bot whose failures a person on review duty already handles (the escalated exit), a supervisor that resumes from the last checkpoint would be the one piece worth adding, more than a journal of model calls.
   - *Do you want to own the context yourself?* Yes: Part F turns on exactly what each call is sent (where a fact sits, what compaction keeps, what the store adds); the context is what the model sees this turn, built from state, memory and the conversation, and building it needs code I control. **My own harness**, not an SDK's loop.

   So: a graph with an on-disk checkpointer and keyed writes, in my own harness, which is what the planned way already is. What the choice does not decide ("framework choice does not answer today's questions"): what to checkpoint, what to remember and for how long, and what to keep when the window fills. Those were Parts A, D and F, and no framework would have made them for me.

## Part F · Find the boundary that lost it

**How the way is told a fact.** A maintainer's note reaches a run through `REPOMIND_NOTE` (who said it: `REPOMIND_NOTE_BY`, default `priya-s`), and `REPOMIND_PART_F` chooses how the run's context is assembled around it (`ways/planned.py`, `told_note`, `fill_request`, `compact`). The run writes a `note` line with the mode. By the write policy, a note from a person with standing is stored when it is read, as a `semantic`, `source: user` record, unless the run has an empty store. The attention and compaction runs used `REPOMIND_STORE=empty`, so that the store, which is not the boundary under test there, could neither add the fact nor older 4192 records. Every run is on 4192, whose answer label is `bug`: without the fact, every 4192 run on my model labelled it `bug` (`2aa362`, `0a0cb7`, `1db603`, `66b243`, and the long-context control `4cbbfe`).

**The facts, word for word, and their effect.** Both make the comment state `label: feature` (`effect: {"label": "feature"}`).

- Compaction and session: "Issue 4192 is a feature request, not a bug: Ledgerline has never re-enabled the Export button after a failed export, and the maintainers want that built as new behaviour. Label it feature."
- Attention: "Nobody ever built a way for the Export button to come back after a failed export; the team thinks of that as work that has not been done yet, rather than something that broke." Worded unlike the question the drafting call answers (a label), because the first fact was used wherever it sat (below).

`eval/forgetting.py` prints, for any run, every model call with its request number, its size, and where the fact sat in it, read as the checker reads it (`request_text`, `squeeze`).

| Case | The lost run | Where it lost the fact (trace and request record) | The fix | The fixed run |
|---|---|---|---|---|
| Attention | `planned-4192-s01-ff046b`: `bug` | Never lost from the window: the drafting call (trace line 24, request 6) was sent 262,177 characters, every file of the repository and its search index, then the run's own results, and the note sat where it landed, at the character midpoint, 128,382 characters from the nearer end. The model labelled it `bug` | Pin the note after everything else, the last thing the drafting call reads | `planned-4192-s01-58d373`: `feature`; request 6, 262,120 characters, the fact 0 characters from the end |
| Compaction | `planned-4192-s01-5888f5`: `bug` | The note arrived with the issue, in step 1's result. Requests 2 and 5 (trace lines 8 and 21) were sent it. Then the `compaction` line (trace line 24: 875 tokens over the 400-token threshold) cleared every tool result but the latest, steps 1 and 2, the issue's among them, and the drafting call, request 6 (line 25), was sent no issue and no note | Clear old tool results, but never the task: the issue's result, with the note that came with it, is kept (Lecture 4: "never summarize the task") | `planned-4192-s01-64716d`: `feature`; the compaction (line 24) cleared step 2 only; request 6 (line 25) was sent the fact, 2,163 characters from an end |
| The session | `planned-4192-s01-66b243`: `bug` | Between runs: it started after the stated run, with an empty store (`store_read`, line 1, returned `[]`), so nothing carried the note over; none of its 7 requests was sent the fact | The memory store: the stated run stored the note as record 14 (`semantic`, `source: user`, `stated_by: priya-s`, issue 4192, confirmed), and the next run read it before planning | `planned-4192-s01-4ad4c6`: `feature`; `store_read` (line 1) returned records 1, 10, 14 and 15 before its first search; requests 2, 5 and 6 (the draft, line 23) were sent the fact, 2,686 characters from an end |

**The session case's stated run:** `planned-4192-s01-760d56`, told the note (mode `plain`): requests 2, 5 and 6 were sent it, it stored it as record 14, and it posted `feature`. One caveat: the fixed run also retrieved record 15, the stated run's own episodic record ("label feature"), so its comment had two records pointing the same way; record 14 holds the fact itself, word for word.

**What it took, and the runs that did not count.** The compaction and session pairs worked on the first try. The attention case took six runs before a lost one, because gpt-4o-mini found the fact wherever I first buried it:

| Run | Fact | The drafting call | Comment |
|---|---|---|---|
| `68fa65` | the first | none: the plan wrote the comment out as a template and the executor never filled it | `<bug \| feature \| question \| docs>` (a bug in the executor, fixed below) |
| `27fb89` | the first | 105,184 characters (`src/` only), the fact 44,887 from an end | `feature`: not lost |
| `0f9dc6` | the second | 134,071 characters (the whole repository), 58,271 from an end | `feature`: not lost |
| `4cbbfe` | none (control) | 133,891 characters | `bug`: the long context alone does not make it `feature` |
| `86b69a` | the second | 262,081 characters (with the search index), the run's results first, 128,481 from an end | `feature`: not lost |
| `ff046b` | the second | 262,177 characters, the run's results last, nearest the draft, 128,382 from an end | `bug`: lost |

Length alone did not lose it, at 26k, 33k or 70k tokens; what lost it was length plus where the rest sat: with the issue's own text ("stays greyed out ... until I reload") after the note and nearer the draft, the buried note lost to it, and pinned after that text it won (`58d373`). That fits the Context Rot results as the lecture gives them: a question worded unlike the needle, and on-topic passages that do not answer it, hurt more than length. It is one pair of runs, not a measurement.

**A bug the attention runs found.** Run `68fa65` posted the placeholder `label: <bug | feature | question | docs>` publicly: the plan had written the comment's body out as a template, without `$fill`, and the executor posts a plan's fixed arguments as they are. The executor now sends any comment body without a valid label to the model to draft (`Executor.prepare`), so a placeholder is never posted.

## AI assistance

I used claude Opus 5.5 to help with coding, bug fixing and re-format my writing
