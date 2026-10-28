# Assignment 4 · Kill it and resume: state, keys and a memory with provenance

Model: <vendor and model>, the same for every run.

## Part A · Mark the plan, place the checkpoints

| Step | Tool | Kind | Checkpoint |
|---|---|---|---|
| 1 | | | |

- Durability mode, and why:
- The weaker of the two writes, and why:

## Part B · Kill it at every step

**The hand walk, written before the matrix.** The crash you expect to be worst:

- Its last checkpoint:
- The steps between it and the crash, and the step running at the crash:
- For each: its side effect, and what closes it (a key, a recorded result, or nothing):

**The matrix, derived keys.** Uncrashed run:

| Step | When | run_id | Comments | Open PRs | Matches its findings |
|---|---|---|---|---|---|

## Part C · Break it on purpose

| Step | When | run_id | Comments | Comment IDs | Open PRs |
|---|---|---|---|---|---|

What the checkpoint did, and what the key did:

## Part D · A memory that can say where it came from

- The write policy, in brief:
- The three candidates, and how each was stored:

| Candidate | Stored? | Kind | source | origin | confirmed | Invites |
|---|---|---|---|---|---|---|
| A | | | | | | |
| B | | | | | | |
| C | | | | | | |

- Eviction: the size, the rule, and how long an entry lives at your write rate:

| Issue 4207, five runs each | With the store | Empty store |
|---|---|---|
| Passes | | |
| Mean tool calls | | |
| Mean tokens | | |

## Part E · Answer from your own runs

1. Your prediction against the matrix:
2. The contradiction test, and the record IDs the third session retrieved:
3. What your checkpoint cost, structured and with the conversation, and over how many runs:
4. Is what you built durable execution?
5. Which abstraction?

## Part F · Find the boundary that lost it

The fact, word for word, and what the comment states when a run uses it:

| Case | The lost run | Where it lost the fact (trace and request record) | The fix | The fixed run |
|---|---|---|---|---|
| Attention | | | | |
| Compaction | | | | |
| The session | | | | |

The session case's stated run:

## AI assistance

Which tool, what it wrote, and what you checked.
