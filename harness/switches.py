"""The four switches of Assignment 3, read from the environment.

Set them on the command line, for one command:

    FLAKY_WRITES=1 python run.py --way planned --set dev --runs 3
    FLAKY_WRITES=1 READBACK_FAIL=1 python run.py --way planned --set dev --runs 3
    FLAKY_WRITES=1 KEY_MODE=uuid VERIFY=off python run.py --way planned --set eval --runs 2 --start-sweep 3

Two make the tracker lie (harness/tracker.py obeys them):

    FLAKY_WRITES    1: some writes time out. Most of them had committed before the
                    connection dropped; the rest never reached the tracker.
    READBACK_FAIL   1: once a write in a run has timed out, every read of that run's
                    comments and pull requests fails too, so the run cannot tell
                    whether the write landed.

Two turn your harness into Part D's naive control. Your registry obeys them
(Assignment 3, Part C, task 6); nothing in harness/ does:

    KEY_MODE        derived (unset): the keys your harness derives
                    uuid: a fresh random key on every attempt
    VERIFY          on (unset): read a failed write back before deciding what to do
                    off: skip that step and retry a failed write blind

The runner records all four in every run's run_start line (`switches`), so the
checker tells Part D's two arms apart from the traces.
"""

from __future__ import annotations

import os

KEY_MODES = ("derived", "uuid")
VERIFY_MODES = ("on", "off")


def _flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value in ("", "0", "off", "false", "no"):
        return False
    if value in ("1", "on", "true", "yes"):
        return True
    raise SystemExit(f"{name}={os.environ[name]!r}: set it to 1, or leave it unset")


def current() -> dict:
    """The four switches as this process sees them. Refuses a value it does not know."""
    key_mode = os.environ.get("KEY_MODE", "").strip().lower() or "derived"
    verify = os.environ.get("VERIFY", "").strip().lower() or "on"
    if key_mode not in KEY_MODES:
        raise SystemExit(f"KEY_MODE={key_mode!r}: one of {KEY_MODES}, or unset for derived")
    if verify not in VERIFY_MODES:
        raise SystemExit(f"VERIFY={verify!r}: one of {VERIFY_MODES}, or unset for on")
    return {"flaky_writes": _flag("FLAKY_WRITES"), "readback_fail": _flag("READBACK_FAIL"),
            "key_mode": key_mode, "verify": verify}


DEFAULTS = {"flaky_writes": False, "readback_fail": False, "key_mode": "derived", "verify": "on"}
