# RepoMind

The course's running system, built one layer at a time. RepoMind triages issues
for **Ledgerline**, a small reporting and export service: it reads an issue,
searches Ledgerline's private codebase, opens a draft pull request for the file it
names, and posts a triage comment where the issue's author can read it.

That combination is deliberate. RepoMind reads text anyone can write, reaches
code nobody outside the team should see, and writes somewhere public. Lecture 1
calls it the lethal trifecta. You build it this way on purpose, and Lecture 8 is
when you close it.

## Start here

You have two things: this repository, and the assignment handout from your
instructor. The handout says what to build and how it is graded; this file says
how the repository works. For Assignment 4, read the handout's "Getting started"
first.

This repository holds Assignment 3's working solution in place of your own code:
the planned way, its five namespaced tools, derived keys, the check before every
write, the three exits and the call record. Your Assignment 3 repository stays as
it is. Nothing in it survives a crash or a run yet: `state/checkpointer.py` and
`state/store.py` are stubs. A fresh copy runs, and `make check-04` awards it
nothing. That is expected.

### What you need

- Python 3.10 or later, `git` and `make`. Python's built-in `sqlite3` is all the
  database this assignment needs.
- The model and API key you used in Assignment 3, or any model with tool calling.
  Never commit the key and never share it.

### Set up, and use your Assignment 3 model

```bash
make setup                     # creates .venv and installs the three dependencies
source .venv/bin/activate      # in every new terminal
make test                      # the harness's own tests; they spend no tokens
```

From your Assignment 3 repository, copy the `provider`, `model`, `base_url` and
`api_key_env` lines of `settings.yaml` into this one, and your model's line in
`pricing.yaml`, if this sheet does not have it. Change nothing else in
`settings.yaml`. Two backends cover almost every vendor:

| Your model | In `settings.yaml` |
|---|---|
| Claude, through Anthropic's API | `provider: anthropic`, `model`; the key in `ANTHROPIC_API_KEY` |
| Anything with an OpenAI-compatible API: OpenAI, Google Gemini, Mistral, DeepSeek, Groq, OpenRouter, a local Ollama or vLLM server, and many more | `provider: openai-compatible`, `model`, `base_url` (none for OpenAI itself), and `api_key_env`, the variable that holds your key (default `OPENAI_API_KEY`) |

Then check it:

```bash
export OPENAI_API_KEY=...      # or the variable your api_key_env names
make ping                      # your key, your model, tool calling, its price line, and your five definitions
```

`make test` and `make ping` must both pass before you write any code.

### Where to start: Assignment 4

| Order | What you write | How you test it | Costs |
|---|---|---|---|
| Part A | `state/checkpointer.py`, and the checkpoint calls in `ways/planned.py` | `python run.py --way planned --issues 4201 --backend harness.scripted:ScriptedTriage`, free; then one run on your model | One run |
| Part B | Resume in `ways/planned.py` | The same scripted model with `--die-after-step N` and `--resume`, free; then `make reset` and the crash matrix on your model | 11 runs and 10 resumes |
| Part C | Nothing new: the same matrix with `KEY_MODE=uuid` | `make reset`, then the matrix again | 10 runs and 10 resumes |
| Part D | `state/write_policy.md`, `state/store.py`, a script that stores the three candidates, and the store read and write in `ways/planned.py` | The scripted model, free; then the seed run and ten runs of issue 4207 | 11 runs |
| Part E | The contradiction test and the checkpoint's size | Scripts of yours | A few runs |
| Part F | A fact your way can be told, and the three ways to lose it and bring it back: buried, compacted, between runs | The scripted model, free; then seven runs on issue 4192 or 4191 | 7 runs |

`make check-04` works at any point and shows what is still missing; it is the same
checker staff run.

## What is here, and what is yours

| Path | What it is | Yours to edit? |
|---|---|---|
| `ways/planned.py`, `agent/`, `prompts/` | Assignment 3's working solution: the plan, its validator, the executor, the comment drafted and checked before either write, the PR before the comment. `ways/notes.py` is Assignment 2's compaction, to borrow from in Part F | **Yes**: your checkpoints, resume, store reads and Part F's switches go in `ways/planned.py` |
| `tools/` | Assignment 3's five tools and their registry. New: every result carries `key`, the idempotency key a write was sent with, and `read_issue` returns an issue's discussion, the comments people wrote on it | **Yes** |
| `state/checkpointer.py`, `state/store.py` | Stubs, with the signatures `checks/FORMATS.md`, section 12, fixes, because the checker calls them | **Yes**: Parts A and D |
| `state/write_policy.md` | You create it | **Yes**: Part D |
| `run.py` | Runs a way over issues. New: `--die-after-step N`, `--die-during-step N` and `--resume <run_id>` | No |
| `harness/` | The model client, tracker, trace writer, runner, prices and scripted models. New for Assignment 4: the kill and the resume, a resumed run's trace going on after a `resume` line, the `checkpoint` and `store_read` events, issue discussions, `make reset` archiving the tracker without moving any run, and the request record: on issues 4191 and 4192, every model request is written to `runs/<run_id>.requests.jsonl` before it is sent | No |
| `fixtures/issues/4207.md` | The reopened issue: closed on 19 August, reopened on 12 October, with its discussion. Its answer is in `fixtures/answers.yaml` | **Never** |
| `fixtures/memory/` | Three candidate memories for RepoMind's store | **Never** |
| `fixtures/` | Everything else: Ledgerline's codebase, the issues and answers, the search index, Assignment 2's plans and traces | **Never** |
| `checks/` | `check_04.py`, the Assignment 4 checker, and `FORMATS.md`, which defines every format it reads (section 12 is new) | No |
| `tests/` | The harness's own tests | No |
| `settings.yaml`, `pricing.yaml` | Your model, the ceilings, the dated price sheet | Once, in setup: your model and its price line; never the ceilings |
| `eval/` | The grounded check, and the earlier assignments' scripts; any script of yours | **Yes** |
| `reports/`, `ARCHITECTURE.md`, `CHANGES.md` | Your write-ups; `reports/` starts with the templates for `LAB_04.md` and `LAB_04.json` | **Yes** |
| `runs/`, `tracker/`, `state/*.db` | Made as you run: traces, call records, request records, the ledger, the tracker's database and its archives, your checkpoint and store databases | Written by the harness and your code; **commit them** |

## Running

```bash
python run.py --way planned --issues 4201                          # one uncrashed run
python run.py --way planned --issues 4201 --die-after-step 3       # killed just after step 3
python run.py --resume <run_id>                                    # the same run again, the same run_id
python run.py --way planned --issues 4201 --die-during-step 4      # killed while step 4 runs
KEY_MODE=uuid python run.py --way planned --issues 4201 --die-during-step 5   # Part C
python run.py --way planned --issues 4207                          # the reopened issue
python run.py --way planned --issues 4192                          # Part F: its request record is runs/<run_id>.requests.jsonl
python run.py --way planned --issues 4201 --backend harness.scripted:ScriptedTriage --die-after-step 2   # free
make reset                                                         # archive the tracker; never between a crash and its resume
make check-04                                                      # the Assignment 4 checker
```

**A step** is one step of the plan, counted in the order the plan's steps first
call a tool: step 1 is the first plan step to call one. In a plan that opens its
PR, step 4 opens the PR and step 5 posts the comment. `--die-after-step N` kills
the process with `kill -9` just after step N's tool call returns, before your way
can save anything after it. `--die-during-step N` kills it while step N runs: for
a write, once the tracker has committed it and before the reply comes back. A
killed run prints its `run_id` as it dies, has no `run_end` line, and keeps a row
in `runs/_ledger.jsonl` with the tokens it spent. `--resume` runs your way again
under the same `run_id`, with the run's own four switches (not variables of your
own: give a resume the same ones), and appends to its trace and call record. Every
run runs anew: nothing is skipped because an earlier run finished.

The tracker stamps every comment and PR with the run that wrote it, and scopes
every read to that run, so each crashed run is counted on its own writes. `make
reset` moves the tracker's database to `tracker/archive/` and starts it empty;
nothing is deleted, and the checker reads the archives too. `KEY_MODE=uuid` gives
every write attempt a fresh random key in place of the derived one; the other three
switches of Assignment 3 stay unset in this assignment. `python run.py --help`
lists every option.

## The rules the harness enforces

- **Success is read from the tracker, never from the agent.** The crash matrix is
  counted from the tracker's database by `run_id`, never from your traces.
- **Every read of the tracker is scoped to one run**, and every write is stamped
  with it.
- **Every run has a hard ceiling** (`session_token_ceiling`), and **every
  assignment has one** (`lab_token_ceiling`); a killed run's tokens count too. The
  runner stops starting runs at the second. Ask before you pass `--over-budget`.
- **The plan is logged before anything runs**, as in Assignment 2.
- **Prompts live in `prompts/`**, and a layer held only by a prompt is empty.
- **Disclose AI assistance** in each report: which tool, what it wrote, what you
  checked.

## Submitting an assignment

Your copy of this repository is private. When you create it, add the course
staff's GitHub account as a collaborator (**Settings**, then **Collaborators**)
and post its URL on the assignment in Canvas: that is how staff find and read
your work.

Run `make check-04` first; it is the same checker staff run. Commit everything,
including `runs/`, `tracker/` with its archives, and your checkpoint and store
databases (the checker reads them all), then tag the commit and push both the
commit and the tag. A tag you have not pushed has not been submitted.

```bash
make check-04
git add -A
git commit -m "Assignment 4"
git tag lab-04
git push
git push origin lab-04
```
