"""Run a way of doing the triage task, kill it at a plan step, or resume it.

    python run.py --way planned --issues 4201                          # one uncrashed run
    python run.py --way planned --issues 4201 --die-after-step 3       # killed just after step 3
    python run.py --way planned --issues 4201 --die-during-step 4      # killed while step 4 runs
    python run.py --resume <run_id>                                    # the crashed run, again, same run_id
    KEY_MODE=uuid python run.py --way planned --issues 4201 --die-during-step 5   # Part C: random keys
    python run.py --way planned --issues 4201 --backend harness.scripted:ScriptedTriage   # free
    python run.py --way planned --set dev                              # the two development issues

A step is one step of the plan, counted in the order the plan's steps first call a
tool: step 1 is the first plan step to call one. --die-after-step N ends the process
with kill -9 just after step N's tool call returns. --die-during-step N ends it
while step N runs: for a write, once the tracker has committed it and before the
reply comes back, so the write happened and the process never learned it; for a
read, before it runs. A killed run's trace has no run_end line; the runner prints
its run_id as it dies, and it is also in the names of the newest files in runs/
(ls -t runs | head -3). Give a kill one issue and one run.

--resume restarts a crashed run under the same run_id: the same way, issue,
backend and switches (its own, whatever the environment says now). Its trace goes
on after a resume line, and its call record is appended to. Your way finds out
that it is a resume by asking your checkpointer for that run_id's last checkpoint.

The four switches (FLAKY_WRITES, READBACK_FAIL, KEY_MODE, VERIFY) are environment
variables, read by harness/switches.py and recorded in every run's run_start line.
Every run runs anew: nothing is skipped because an earlier run finished. Success is
not decided here: eval/check_triage.py reads the tracker for each run_id.

`make reset` archives the tracker's database to tracker/archive/ and starts it
empty; it leaves runs/ as it is. Never run it between a crash and its resume.
"""

import argparse
import sys

from harness import switches
from harness.runner import QUOTA_MESSAGE, discard, resume_run, run_sweeps
from harness.tracker import Tracker


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--way", help="a module in ways/: direct, workflow, agent, hybrid, planned, notes")
    p.add_argument("--set", default="dev", choices=["dev", "eval"], help="which issues (default dev)")
    p.add_argument("--issues", help="comma-separated issue numbers; overrides --set")
    p.add_argument("--runs", type=int, default=1, help="sweeps over the issues (default 1)")
    p.add_argument("--start-sweep", type=int, default=1, help="number of the first sweep")
    p.add_argument("--backend", help="default: the provider in settings.yaml; never-stops, or a harness.scripted: model, tests your code for free")
    p.add_argument("--jobs", type=int, help="runs at once (default from settings.yaml)")
    p.add_argument("--critique", default="off", choices=["off", "self", "external"],
                   help="the second pass before posting (default off); recorded in run_start")
    p.add_argument("--notes", default="off", choices=["off", "on"],
                   help="show the progress file to the model (default off); recorded in run_start")
    die = p.add_mutually_exclusive_group()
    die.add_argument("--die-after-step", type=int, metavar="N", help="kill -9 just after plan step N's tool call returns")
    die.add_argument("--die-during-step", type=int, metavar="N",
                     help="kill -9 while plan step N runs: a write once the tracker commits it, before its reply")
    die.add_argument("--resume", metavar="RUN_ID", help="run a crashed run's way again, under its own run_id")
    p.add_argument("--over-budget", action="store_true", help="ignore the assignment's token ceiling (ask first)")
    p.add_argument("--discard", action="store_true",
                   help="move this configuration's runs on these issues, and their rows in the tracker, to "
                        "runs/discarded/; their tokens stay in the ledger")
    a = p.parse_args(argv)

    if a.resume:
        row = resume_run(a.resume, over_budget=a.over_budget)
        if row.get("quota"):
            print(QUOTA_MESSAGE)
        return 1 if row["error"] and not (row["quota"] or row["rate_limited"]) else 0
    if not a.way:
        p.error("--way is required, unless you --resume a run")
    issues = ([int(x) for x in a.issues.split(",")] if a.issues
              else Tracker(flaky=False, readback_fail=False).issue_numbers(a.set))
    if a.discard:
        discard(a.way, issues, critique=a.critique, notes=a.notes, switches=switches.current())
        return 0
    kill = (("after", a.die_after_step) if a.die_after_step is not None
            else ("during", a.die_during_step) if a.die_during_step is not None else None)
    if kill and kill[1] < 1:
        p.error("plan steps are numbered from 1")
    sweeps = range(a.start_sweep, a.start_sweep + a.runs)
    rows = run_sweeps(a.way, issues, sweeps, a.backend, jobs=1 if kill else a.jobs, over_budget=a.over_budget,
                      critique=a.critique, notes=a.notes, die=kill)
    tokens = sum(r["total_tokens"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    errors = sum(1 for r in rows if r["error"] and not (r["quota"] or r["rate_limited"]))
    print(f"\n{len(rows)} runs, {tokens:,} tokens, ${cost:.4f}, {errors} with errors")
    limited = sum(1 for r in rows if r["rate_limited"])
    if limited:
        print(f"{limited} runs stopped by rate limits are not finished: run the same command again to redo them"
              " (add --jobs 1 on a free tier)")
    if any(r["quota"] for r in rows):
        print(QUOTA_MESSAGE)
        return 0
    return 1 if errors == len(rows) and rows else 0


if __name__ == "__main__":
    sys.exit(main())
