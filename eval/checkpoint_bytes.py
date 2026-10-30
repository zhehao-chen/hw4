"""Assignment 4, Part E, task 3: what one run's checkpoints cost, without and with the conversation.

    python eval/checkpoint_bytes.py RUN_ID ...       # runs on 4191 or 4192, which have a request record

Structured: every checkpoint the run saved through state/checkpointer.py, as the
JSON it stores, summed. With the conversation: the same checkpoints, each with
everything the run had sent the model and received back by then (the request
record's system prompt, messages and tool names, and each response's text and tool
calls from the trace), saved to state/checkpoints_conversation.db, never through
the checkpointer. Prints both per run and the means.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import ROOT  # noqa: E402
from state.checkpointer import Checkpointer  # noqa: E402

OTHER = ROOT / "state" / "checkpoints_conversation.db"


def jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def measure(run_id: str, db: sqlite3.Connection) -> tuple[int, int, int]:
    saved = Checkpointer().all(run_id)
    trace = jsonl(ROOT / "runs" / f"{run_id}.jsonl")
    requests = {r["n"]: r for r in jsonl(ROOT / "runs" / f"{run_id}.requests.jsonl")}
    conversation, marks = [], []
    for line in trace:                     # the conversation as it stood at each checkpoint line
        if line.get("type") == "model_call" and line.get("request") in requests:
            req = requests[line["request"]]
            conversation.append({"request": {k: req.get(k) for k in ("system", "messages", "tools")},
                                 "response": {"text": line.get("text"), "tool_calls": line.get("tool_calls")}})
        elif line.get("type") == "checkpoint":
            marks.append(len(conversation))
    if len(marks) != len(saved):
        raise SystemExit(f"{run_id}: {len(saved)} checkpoints saved, {len(marks)} checkpoint lines")
    structured = with_conversation = 0
    db.execute("DELETE FROM checkpoints WHERE run_id = ?", (run_id,))
    for i, (cp, upto) in enumerate(zip(saved, marks)):
        structured += size(cp)
        whole = json.dumps({**cp, "conversation": conversation[:upto]}, ensure_ascii=False)
        with_conversation += len(whole.encode("utf-8"))
        db.execute("INSERT INTO checkpoints VALUES (?, ?, ?)", (run_id, i, whole))
    db.commit()
    return len(saved), structured, with_conversation


def main() -> None:
    db = sqlite3.connect(OTHER)
    db.execute("CREATE TABLE IF NOT EXISTS checkpoints (run_id TEXT, n INTEGER, checkpoint TEXT)")
    rows = [(rid, *measure(rid, db)) for rid in sys.argv[1:]]
    for rid, n, s, c in rows:
        print(f"{rid}: {n} checkpoints, structured {s:,} bytes, with the conversation {c:,} bytes ({c / s:.1f}x)")
    k = len(rows)
    out = {"structured": round(sum(r[2] for r in rows) / k), "with_conversation": round(sum(r[3] for r in rows) / k),
           "runs": k}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
