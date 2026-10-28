"""The harness's Assignment 4 additions: the reopened issue and its discussion, the
tracker's commit hook, the resume line, the two new events, how the runner numbers
plan steps for run.py --die-after-step and --die-during-step, and Part F's request
record. They spend no tokens, never kill this process, and keep passing once your
state/ is written."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from harness import LAB, ROOT
from harness.client import ModelClient
from harness.formats import CHECKPOINT_FIELDS, RECORDED_ISSUES, SENTINEL, request_text, squeeze
from harness.pricing import PriceSheet
from harness.runner import WayContext, is_trace, request_record, resume_run
from harness.scripted import ScriptedTriage, role_call
from harness.settings import load_settings
from harness.trace import TraceWriter, read_trace
from harness.tracker import Tracker
from tools import RunContext, default_tools

REOPENED = 4207


def tracker(tmp: str, **kw) -> Tracker:
    return Tracker(ROOT, state_dir=Path(tmp) / "tracker", flaky=False, readback_fail=False, **kw)


class ReopenedIssueTests(unittest.TestCase):
    def test_the_reopened_issue_and_its_discussion(self):
        with tempfile.TemporaryDirectory() as tmp:
            issue = tracker(tmp).issue(REOPENED)
        self.assertEqual(str(issue["closed"]), "2026-08-19")
        self.assertEqual(str(issue["reopened"]), "2026-10-12")
        self.assertTrue(issue["body"].rstrip().endswith("-->"), "the sentinel stays the body's last line")
        self.assertEqual(len(SENTINEL.findall(issue["body"])), 1)
        people = [(c["author"], c["role"]) for c in issue["discussion"]]
        self.assertEqual(people, [("priya-s", "maintainer"), ("dvasquez", None), ("priya-s", "maintainer")])
        self.assertNotIn("## Discussion", issue["body"])

    def test_an_issue_with_no_discussion(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(tracker(tmp).issue(4201)["discussion"], [])

    def test_read_issue_returns_the_discussion_and_never_a_runs_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = tracker(tmp)
            t.post_comment("run-a", REOPENED, "label: bug\nfile: written-by-a-run")
            tools = default_tools(RunContext(run_id="run-a", tracker=t, repo_root=ROOT / "fixtures" / "repo"))
            name, args = role_call("read_issue", number=REOPENED)
            result = tools.call(name, args)
        self.assertFalse(result.is_error, result.content)
        self.assertIn("priya-s", result.content)
        self.assertIn("reopened", result.content.lower())
        self.assertNotIn("written-by-a-run", result.content)

    def test_its_answer_names_a_file_that_exists(self):
        answers = yaml.safe_load((ROOT / "fixtures" / "answers.yaml").read_text())["eval"]
        self.assertEqual(answers[REOPENED]["label"], "bug")
        self.assertTrue((ROOT / "fixtures" / "repo" / answers[REOPENED]["file"]).is_file())

    def test_the_three_memory_candidates(self):
        found = sorted((ROOT / "fixtures" / "memory").glob("*.yaml"))
        self.assertEqual(len(found), 3)
        for path in found:
            data = yaml.safe_load(path.read_text())
            for key in ("candidate", "repository", "issue", "who", "where", "when", "seen"):
                self.assertIn(key, data, f"{path.name}: {key}")


class CommitHookTests(unittest.TestCase):
    def test_the_hook_runs_once_the_write_is_committed(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            t = tracker(tmp)
            t.on_commit = lambda run_id, kind: seen.append((run_id, kind, len(t.comments(run_id))))
            t.post_comment("run-a", 4201, "label: bug\nfile: x")
        self.assertEqual(seen, [("run-a", "comment", 1)], "the comment is in the database when the hook runs")

    def test_no_hook_for_a_write_that_never_committed(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            t = tracker(tmp, faults=["before_commit"])
            t.on_commit = lambda run_id, kind: seen.append(kind)
            with self.assertRaises(Exception):
                t.post_comment("run-a", 4201, "x")
        self.assertEqual(seen, [])


class TraceTests(unittest.TestCase):
    def test_a_resume_appends_after_a_resume_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            first = TraceWriter(path, "run-a", {"lab": LAB})
            first.event("checkpoint", step=3, mode="sync")
            first.close()
            again = TraceWriter(path, "run-a", {"resumed": 1}, resume=True)
            again.run_end({"total_tokens": 0}, None)
            types = [r["type"] for r in read_trace(path)]
        self.assertEqual(types, ["run_start", "checkpoint", "resume", "end", "run_end"])

    def test_the_two_new_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = TraceWriter(Path(tmp) / "t.jsonl", "run-a", {})
            trace.event("store_read", issue=REOPENED, records=[])
            with self.assertRaises(ValueError):
                trace.event("checkpoint", step=1, mode="sometimes")
            with self.assertRaises(ValueError):
                trace.event("checkpoint", step=1)
            with self.assertRaises(ValueError):
                trace.event("store_read", issue=REOPENED, records="r1")
            with self.assertRaises(ValueError):
                trace.event("resume")
            trace.close()
        self.assertEqual(CHECKPOINT_FIELDS, ("plan", "step_status", "completed_calls", "findings", "current_step"))


class StepNumberTests(unittest.TestCase):
    def context(self, tmp: str, die=None) -> WayContext:
        settings = load_settings(ROOT / "settings.yaml")
        t = tracker(tmp)
        tools = default_tools(RunContext(run_id="run-a", tracker=t, repo_root=ROOT / "fixtures" / "repo"))
        client = ModelClient(ScriptedTriage(), PriceSheet(ROOT / "pricing.yaml"))
        trace = TraceWriter(Path(tmp) / "t.jsonl", "run-a", {})
        return WayContext("run-a", 4201, client, tools, trace, t, settings, ROOT, runs_dir=Path(tmp), die=die)

    def test_steps_are_numbered_as_they_first_call_a_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.context(tmp)
            self.assertEqual([ctx.step_number(s) for s in ("1", "2", "1", "7", "3")], [1, 2, 1, 3, 4])
            self.assertIsNone(ctx.step_number(None))
            ctx.trace.close()

    def test_die_after_a_step_stops_once_its_call_returns(self):
        stops = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.context(tmp, die=("after", 2))
            ctx.on_die = stops.append
            for step, role, values in (("1", "read_issue", {"number": 4201}), ("2", "search", {"query": "localhost"})):
                name, args = role_call(role, **values)
                ctx.call_tool(0, name, args, plan_step=step)
            ctx.trace.close()
        self.assertEqual(len(stops), 1)
        self.assertTrue(stops[0].startswith("after step 2"), stops)

    def test_die_during_a_write_stops_once_the_tracker_commits_it(self):
        stops = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.context(tmp, die=("during", 1))
            ctx.on_die = lambda when: stops.append((when, len(ctx.tracker.comments("run-a"))))
            name, args = role_call("comment", number=4201, body="label: bug\nfile: src/notifications/templates.ts")
            ctx.call_tool(0, name, args, plan_step="5")
            ctx.trace.close()
        self.assertEqual(len(stops), 1)
        self.assertTrue(stops[0][0].startswith("during step 1"), stops)
        self.assertEqual(stops[0][1], 1, "the comment was committed before the stop")

    def test_a_finished_run_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            (runs / "run-a.jsonl").write_text(json.dumps({"type": "run_start", "lab": LAB, "run_id": "run-a"}) + "\n"
                                              + json.dumps({"type": "run_end", "run_id": "run-a"}) + "\n")
            with self.assertRaises(SystemExit) as raised:
                resume_run("run-a", root=Path(tmp))
            self.assertIn("nothing to resume", str(raised.exception))


class RequestRecordTests(unittest.TestCase):
    def test_every_request_is_recorded_and_numbered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run-a.requests.jsonl"
            client = ModelClient(ScriptedTriage(), PriceSheet(ROOT / "pricing.yaml"), requests=path, run_id="run-a")
            first = client.create(system="sys", messages=[{"role": "user", "content": "Triage issue #4192."}])
            second = client.create(messages=[{"role": "user", "content": [{"type": "text", "text": "again"}]}])
            lines = [json.loads(x) for x in path.read_text().splitlines()]
            again = ModelClient(ScriptedTriage(), PriceSheet(ROOT / "pricing.yaml"), requests=path, run_id="run-a")
            third = again.create(messages=[{"role": "user", "content": "a resume"}])
        self.assertEqual([first.request, second.request, third.request], [1, 2, 3], "a resume goes on numbering")
        self.assertEqual([x["n"] for x in lines], [1, 2])
        self.assertEqual(lines[0]["system"], "sys")
        self.assertIn("Triage issue #4192.", request_text(lines[0]))
        self.assertIn("again", request_text(lines[1]))

    def test_no_record_without_a_path(self):
        client = ModelClient(ScriptedTriage(), PriceSheet(ROOT / "pricing.yaml"))
        self.assertIsNone(client.create(messages=[{"role": "user", "content": "x"}]).request)

    def test_only_the_development_issues_are_recorded(self):
        self.assertEqual(RECORDED_ISSUES, (4191, 4192))
        runs = Path("/tmp/runs")
        self.assertEqual(request_record(runs, "r", 4192), runs / "r.requests.jsonl")
        self.assertIsNone(request_record(runs, "r", 4201))
        self.assertFalse(is_trace(runs / "r.requests.jsonl"), "a request record is not a trace")

    def test_the_trace_names_the_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = ModelClient(ScriptedTriage(), PriceSheet(ROOT / "pricing.yaml"),
                                 requests=Path(tmp) / "r.requests.jsonl", run_id="r")
            trace = TraceWriter(Path(tmp) / "r.jsonl", "r", {})
            trace.model_call(1, client.create(messages=[{"role": "user", "content": "x"}]), purpose="execute")
            trace.close()
            line = read_trace(Path(tmp) / "r.jsonl")[1]
        self.assertEqual(line["request"], 1)

    def test_squeeze(self):
        self.assertEqual(squeeze("  A  rule,\n  stated. "), "a rule, stated.")


if __name__ == "__main__":
    unittest.main()
