"""The harness's own tests. They spend no tokens: `make test`.

Since Assignment 3 they call your tools by role (tools/roles.yaml), written as each
tool's first example writes it, so they keep passing after you rename a tool or an
argument. The few that describe the starter's weak stubs skip once you rewrite them.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from harness import LAB, ROOT
from harness.backends import (DailyQuotaReached, RateLimited, from_openai_response, is_daily_quota, retry_delay,
                               to_openai_messages, to_openai_tools, with_retries)
from harness.client import BudgetExceeded, ModelClient, Usage
from harness.formats import SENTINEL, TERMINAL_REASONS, normalize_path, parse_triage_comment, result_paths
from harness.pricing import PriceSheet
from harness.runner import WayContext, discard, finished_pairs, is_free, to_run
from harness.schema import errors
from harness.scripted import (OFF_PLAN_MARK, AlwaysInvalidPlanner, DraftNamesMissingFile, NeverStops,
                              NoCommentPlanner, OffPlanExecutor, RecordingPlanner, RefusesToRead,
                              SchemaBreakingPlanner, ScriptedTriage, SentinelSearcher, plan_tool, triage_steps)
from harness.trace import TraceWriter, read_trace
from harness.tracker import ReadbackUnavailable, Tracker, TrackerTimeout
from harness.roles import ROLES, arg, tool_for
from harness.scripted import role_call
from tools import RunContext, default_tools

STUB_SEARCH = hashlib.sha256((ROOT / "tools" / "search_repo.json").read_bytes()).hexdigest()[:16] == "acffdab5ed88b3bd"
STARTER_NAMES = tool_for("search") == "search_repo" and tool_for("comment") == "post_comment"


def call(tools, role, **values):
    """Call the tool that plays `role`, with the role's arguments set to `values`."""
    name, args = role_call(role, **values)
    return tools.call(name, args)


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tracker = Tracker(ROOT, state_dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_comments_are_stamped_and_filtered_by_run(self):
        self.tracker.post_comment("run-a", 4191, "label: docs\nfile: README.md")
        self.tracker.post_comment("run-b", 4191, "label: bug\nfile: none")
        self.assertEqual(len(self.tracker.comments(run_id="run-a")), 1)
        self.assertEqual(self.tracker.comments(run_id="run-b")[0]["body"], "label: bug\nfile: none")

    def test_the_model_never_sees_comments(self):
        self.tracker.post_comment("run-a", 4191, "THE ANSWER IS README.md")
        tools = default_tools(RunContext("run-b", self.tracker, ROOT / "fixtures" / "repo"))
        self.assertNotIn("THE ANSWER", call(tools, "read_issue", number=4191).content)

    def test_post_comment_is_stamped_with_the_registry_run(self):
        tools = default_tools(RunContext("run-z", self.tracker, ROOT / "fixtures" / "repo"))
        call(tools, "comment", number=4192, body="label: bug\nfile: x")
        self.assertEqual(self.tracker.comments("run-z", issue=4192)[0]["run_id"], "run-z")

    def test_unknown_issue_is_an_error_result_not_a_crash(self):
        tools = default_tools(RunContext("run-a", self.tracker, ROOT / "fixtures" / "repo"))
        self.assertTrue(call(tools, "read_issue", number=1).is_error)


class SearchTests(unittest.TestCase):
    def test_config_is_outside_the_search_root(self):
        tools = default_tools(RunContext("r", Tracker(ROOT), ROOT / "fixtures" / "repo"))
        name, args = role_call("search", query="sk-FAKE")
        result = tools.call(name, args)
        self.assertEqual(result_paths(name, args, result.content, result.is_error), [])


class FormatTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_triage_comment("Label: Bug\nFILE: `./src/a.ts`\n\nwhy"), ("bug", "src/a.ts"))
        self.assertEqual(parse_triage_comment("label: question\nfile: None"), ("question", "none"))
        self.assertEqual(parse_triage_comment("no lines here"), (None, None))

    def test_normalize(self):
        self.assertEqual(normalize_path("fixtures/repo/src/x.ts"), "src/x.ts")


class ClientTests(unittest.TestCase):
    def test_price_every_token_class(self):
        prices = PriceSheet()
        usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_read_input_tokens=1_000_000)
        price = prices.models["claude-opus-5"]
        self.assertAlmostEqual(prices.cost("claude-opus-5", usage), price.input + price.cache_read)
        self.assertIsNone(prices.cost("not-a-model", usage))

    def test_harness_ceiling_stops_the_next_call(self):
        client = ModelClient(NeverStops(), PriceSheet(), session_ceiling=500)
        with self.assertRaises(BudgetExceeded):
            for _ in range(100):
                client.create(messages=[{"role": "user", "content": "x" * 400}], tools=None)

    def test_never_stops_always_asks_for_a_tool(self):
        tool = {"name": "search_repo", "input_schema": {"properties": {"query": {}}}}
        client = ModelClient(NeverStops(), PriceSheet())
        response = client.create(messages=[{"role": "user", "content": "go"}], tools=[tool])
        self.assertEqual(response.stop_reason, "tool_use")
        self.assertEqual(response.tool_calls[0].name, "search_repo")



class OpenAICompatibleTests(unittest.TestCase):
    """The translation to and from OpenAI-compatible APIs, with no network."""

    def test_a_tool_loop_translates_both_ways(self):
        content, stop, model, usage = from_openai_response({
            "model": "some-model-2026-01-01",
            "choices": [{"finish_reason": "tool_calls", "message": {
                "content": "Reading it.",
                "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": "read_issue", "arguments": '{"number": 4191}'}}]}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 40,
                      "prompt_tokens_details": {"cached_tokens": 300}},
        }, "some-model")
        self.assertEqual(stop, "tool_use")
        self.assertEqual(model, "some-model-2026-01-01")
        self.assertEqual(content[1], {"type": "tool_use", "id": "call_1", "name": "read_issue", "input": {"number": 4191}})
        self.assertEqual((usage.input_tokens, usage.cache_read_input_tokens, usage.prompt_tokens), (600, 300, 900))

        wire = to_openai_messages("Be brief.", [
            {"role": "user", "content": "Triage issue #4191."},
            {"role": "assistant", "content": content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "#4191 ..."}]},
        ])
        self.assertEqual([m["role"] for m in wire], ["system", "user", "assistant", "tool"])
        self.assertEqual(wire[2]["tool_calls"][0]["function"]["name"], "read_issue")
        self.assertEqual(wire[3]["tool_call_id"], "call_1")

    def test_a_vendor_signature_on_a_tool_call_goes_back_unchanged(self):
        signature = {"google": {"thought_signature": "sig-xyz"}}
        content, _, _, _ = from_openai_response({"choices": [{"finish_reason": "stop", "message": {
            "tool_calls": [{"id": "c1", "type": "function", "extra_content": signature,
                            "function": {"name": "echo", "arguments": "{}"}}]}}]}, "m")
        wire = to_openai_messages(None, [{"role": "assistant", "content": content}])
        self.assertEqual(wire[0]["tool_calls"][0]["extra_content"], signature)

    def test_a_rate_limit_waits_as_long_as_the_vendor_asks(self):
        self.assertEqual(retry_delay(Exception("Quota exceeded. Please retry in 36.2s."), 0), 37.2)
        self.assertEqual(retry_delay(Exception("{'retryDelay': '12s'}"), 0), 13.0)
        self.assertEqual(retry_delay(Exception("slow down"), 1), 10.0)
        self.assertEqual(retry_delay(Exception("Please retry in 4000s"), 0), 90.0)

        class Refusal(Exception):
            class response:
                headers = {"retry-after": "7"}
        self.assertEqual(retry_delay(Refusal("Too many requests"), 0), 8.0)

    def test_finish_reasons_and_tools(self):
        _, stop, _, _ = from_openai_response(
            {"choices": [{"finish_reason": "stop", "message": {"content": "label: docs"}}]}, "m")
        self.assertEqual(stop, "end_turn")
        _, stop, _, _ = from_openai_response(
            {"choices": [{"finish_reason": "length", "message": {"content": "lab"}}]}, "m")
        self.assertEqual(stop, "max_tokens")
        tools = to_openai_tools([{"name": "search_repo", "description": "Search.",
                                  "input_schema": {"type": "object", "properties": {}}}])
        self.assertEqual(tools[0]["function"]["parameters"], {"type": "object", "properties": {}})

    def test_a_dated_model_name_finds_its_price_line(self):
        prices = PriceSheet(ROOT / "pricing.yaml")
        self.assertIsNotNone(prices.find("claude-haiku-4-5-20251001"))
        self.assertIsNone(prices.find("no-such-model"))


class ReadFileTests(unittest.TestCase):
    """Assignment 2's fourth tool: a whole file, from the same files search_repo searches."""

    def setUp(self):
        self.tools = default_tools(RunContext("r", Tracker(ROOT), ROOT / "fixtures" / "repo"))

    def test_reads_a_file_by_the_path_search_prints(self):
        result = call(self.tools, "read_file", path="src/exportUtils.ts")
        self.assertFalse(result.is_error)
        self.assertIn("SUPPORTED_FORMATS", result.content)
        self.assertEqual(call(self.tools, "read_file", path="./src/exportUtils.ts").content, result.content)

    def test_stays_inside_the_search_root(self):
        for path in ("../issues/4201.md", "/etc/hosts", "config/secrets.env", "no/such/file.ts", ""):
            self.assertTrue(call(self.tools, "read_file", path=path).is_error, path)

    def test_five_tools_in_order(self):
        self.assertEqual(self.tools.names(), [tool_for(role) for role in ROLES])


class TraceTests(unittest.TestCase):
    """Assignment 2's trace lines: plan, events, purpose, and the escalated ending."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "run.jsonl"
        self.trace = TraceWriter(self.path, "run-x", {"lab": LAB, "way": "test"})
        self.response = ModelClient(NeverStops(), PriceSheet()).create(messages=[{"role": "user", "content": "go"}])

    def tearDown(self):
        self.trace.close()
        self.tmp.cleanup()

    def lines(self):
        self.trace.run_end({}, None)
        return read_trace(self.path)

    def test_plan_event_and_purpose_lines(self):
        plan = {"meta": {"tools": ["read_issue"]}, "steps": triage_steps(4191)[:1]}
        self.trace.model_call(0, self.response, purpose="plan")
        self.trace.plan(1, plan)
        self.trace.event("off_plan", step=2, tool="post_comment", input={})
        self.trace.event("revision", checkpoint="after_search", version=2, valid=False)
        self.trace.end("escalated", detail="no valid plan")
        types = [r["type"] for r in self.lines()]
        self.assertEqual(types, ["run_start", "model_call", "plan", "off_plan", "revision", "end", "run_end"])
        records = read_trace(self.path)
        self.assertEqual(records[1]["purpose"], "plan")
        self.assertEqual(records[2]["plan"], plan)
        self.assertEqual(records[5]["terminal_reason"], "escalated")

    def test_the_trace_refuses_what_a_checker_could_not_read(self):
        with self.assertRaises(ValueError):
            self.trace.model_call(1, self.response, purpose="planning")
        with self.assertRaises(ValueError):
            self.trace.plan(0, {"steps": []})
        with self.assertRaises(ValueError):
            self.trace.plan(1, [{"id": 1}])
        with self.assertRaises(ValueError):
            self.trace.event("tool_call", name="x")
        with self.assertRaises(ValueError):
            self.trace.event("off_plan", tool="post_comment")       # no step
        with self.assertRaises(ValueError):
            self.trace.event("revision", checkpoint="c", version=2)  # no valid

    def test_the_second_pass_and_part_g_lines(self):
        self.trace.model_call(3, self.response, purpose="critique")
        self.trace.event("critique", round=1, mode="external", result="fail", reason="never saw it",
                         changed=True, draft="label: bug\nfile: x.ts")
        self.trace.event("compaction", threshold=300, tokens=412)
        self.trace.event("question", path="src/a.ts", answer="no")
        types = [r["type"] for r in self.lines()]
        self.assertEqual(types[1:5], ["model_call", "critique", "compaction", "question"])
        other = TraceWriter(Path(self.tmp.name) / "b.jsonl", "b", {})
        with self.assertRaises(ValueError):
            other.event("critique", round=1, mode="self")
        other.close()

    def test_a_tool_call_records_the_paths_it_returned(self):
        self.assertEqual(result_paths("search_repo", {"query": "x"}, "src/a.ts:3: x\nsrc/a.ts:9: x\nREADME.md:1: x", False),
                         ["src/a.ts", "README.md"])
        self.assertEqual(result_paths("read_file", {"path": "./src/b.ts"}, "code", False), ["src/b.ts"])
        self.assertEqual(result_paths("read_issue", {"number": 1}, "src/c.ts:1: planted", False), [])
        self.assertEqual(result_paths("read_file", {"path": "x"}, "Error", True), [])

    def test_a_tool_call_names_its_plan_step(self):
        tools = default_tools(RunContext("r", Tracker(ROOT), ROOT / "fixtures" / "repo"))
        ctx = WayContext("r", 4191, None, tools, self.trace, None, None, ROOT)
        ctx.call_tool(1, *role_call("search", query="dedupeKey"), plan_step=2)
        ctx.call_tool(1, *role_call("read_issue", number=4191))
        calls = [r for r in self.lines() if r["type"] == "tool_call"]
        self.assertEqual([c["plan_step"] for c in calls], [2, None])
        self.assertEqual(calls[0]["paths"], ["src/ingest/dedupe.ts"])

    def test_a_call_with_no_purpose_is_recorded_as_null(self):
        self.trace.model_call(1, self.response)
        self.assertIsNone(self.lines()[1]["purpose"])

    def test_escalated_quota_and_rate_limited_are_terminal_reasons(self):
        for reason in ("escalated", "quota", "rate_limited"):
            self.assertIn(reason, TERMINAL_REASONS)


class Assignment2HarnessTests(unittest.TestCase):
    def test_runs_are_recorded_as_this_assignment(self):
        self.assertEqual(LAB, "04")

    def test_strict_goes_through_as_function_strict(self):
        tool = {"name": "submit_plan", "description": "d", "strict": True,
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}}
        self.assertIs(to_openai_tools([tool])[0]["function"]["strict"], True)
        plain = dict(tool)
        del plain["strict"]
        self.assertNotIn("strict", to_openai_tools([plain])[0]["function"])

    def test_the_modes_reach_the_way(self):
        ctx = WayContext("r-1", 4191, None, None, None, None, None, ROOT, critique="self", notes="on",
                         runs_dir=Path("/tmp/x"))
        self.assertEqual((ctx.critique, ctx.notes), ("self", "on"))
        self.assertEqual(ctx.progress_path, Path("/tmp/x/r-1.progress.json"))
        self.assertEqual(WayContext("r-2", 1, None, None, None, None, None, ROOT).critique, "off")

    def test_scripted_models_are_free(self):
        self.assertTrue(is_free("never-stops"))
        self.assertTrue(is_free("harness.scripted:OffPlanExecutor"))
        self.assertFalse(is_free("openai-compatible"))

    def test_every_issue_carries_one_sentinel(self):
        tracker = Tracker(ROOT)
        found = []
        for number in tracker.issue_numbers("eval") + tracker.issue_numbers("dev"):
            sentinels = SENTINEL.findall(tracker.issue(number)["body"])
            self.assertEqual(len(sentinels), 1, number)
            found += sentinels
        self.assertEqual(len(found), len(set(found)))


class SchemaTests(unittest.TestCase):
    """harness.schema.errors: what strict mode promises, checked in code."""

    STEP = {"type": "object", "additionalProperties": False, "required": ["id", "tool", "status"],
            "properties": {"id": {"type": "integer"}, "tool": {"type": ["string", "null"]},
                           "status": {"type": "string", "enum": ["pending", "done"]}}}
    PLAN = {"type": "object", "additionalProperties": False, "required": ["steps"],
            "properties": {"steps": {"type": "array", "items": {"$ref": "#/$defs/step"}}}, "$defs": {"step": STEP}}

    def test_a_plan_that_fits(self):
        self.assertEqual(errors({"steps": [{"id": 1, "tool": None, "status": "done"}]}, self.PLAN), [])

    def test_every_way_a_plan_can_break_it(self):
        found = errors({"steps": [{"id": "1", "status": "later", "note": 1}, 7], "extra": True}, self.PLAN)
        self.assertEqual(len(found), 6, found)
        self.assertTrue(any(f.startswith("steps[0].tool: required") for f in found))
        self.assertTrue(any(f.startswith("steps[0].note: not in the schema") for f in found))
        self.assertTrue(any(f.startswith("steps[0].id: string") for f in found))
        self.assertTrue(any("steps[1]: integer" in f for f in found))

    def test_one_shape_of_several(self):
        args = {"oneOf": [{"type": "object", "additionalProperties": False, "required": ["query"],
                           "properties": {"query": {"type": "string"}}},
                          {"type": "object", "additionalProperties": False, "required": ["path"],
                           "properties": {"path": {"type": "string"}}}]}
        self.assertEqual(errors({"query": "x"}, args), [])
        self.assertEqual(len(errors({"number": 1}, args)), 1)


class QuotaAndResumeTests(unittest.TestCase):
    """A daily quota stops a sweep; the same command resumes it; --discard starts it over."""

    def test_a_daily_quota_is_told_from_a_minute_one(self):
        self.assertTrue(is_daily_quota(Exception(
            "429 Quota exceeded for metric: generate_content_free_tier_requests, quotaId: "
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier")))
        self.assertTrue(is_daily_quota(Exception("You exceeded your daily request limit")))
        self.assertFalse(is_daily_quota(Exception(
            "429 quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier. Please retry in 36.2s.")))

    class Refused(Exception):
        def __init__(self, status, text="Too many requests", after="0"):
            super().__init__(text)
            self.status_code = status
            self.response = type("R", (), {"status_code": status, "headers": {"retry-after": after}})()

    def test_both_backends_wait_out_a_rate_limit_or_an_overload(self):
        waits, calls = [], iter([self.Refused(429), self.Refused(529, "overloaded_error"), "reply"])

        def call():
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item
        self.assertEqual(with_retries(call, sleep=waits.append), "reply")
        self.assertEqual(waits, [1.0, 1.0])   # retry-after 0, plus a second

    def test_a_refusal_that_outlasts_the_retries_ends_the_run_rate_limited(self):
        def call():
            raise self.Refused(429)
        with self.assertRaises(RateLimited):
            with_retries(call, sleep=lambda s: None)
        with self.assertRaises(DailyQuotaReached):
            with_retries(lambda: (_ for _ in ()).throw(self.Refused(429, "quotaId: RequestsPerDay")),
                         sleep=lambda s: None)
        with self.assertRaises(ValueError):   # anything else is not a refusal to wait out
            with_retries(lambda: (_ for _ in ()).throw(ValueError("bad request")), sleep=lambda s: None)

    def write_run(self, runs, run_id, end="completed", critique="self", backend="openai-compatible"):
        lines = [{"type": "run_start", "run_id": run_id, "lab": LAB, "way": "planned", "issue": 4201, "sweep": 1,
                  "backend": backend, "critique": critique, "notes": "off"},
                 {"type": "end", "run_id": run_id, "terminal_reason": end}, {"type": "run_end", "run_id": run_id}]
        (runs / f"{run_id}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))

    def test_only_finished_runs_of_the_same_configuration_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            self.write_run(runs, "a", end="quota")
            self.write_run(runs, "a2", end="rate_limited")
            self.assertEqual(finished_pairs(runs, "planned", "self", "off", "openai-compatible"), set())
            self.write_run(runs, "b")
            self.assertEqual(finished_pairs(runs, "planned", "self", "off", "openai-compatible"), {(1, 4201)})
            self.assertEqual(finished_pairs(runs, "planned", "external", "off", "openai-compatible"), set())
            self.assertEqual(finished_pairs(runs, "planned", "self", "off", "anthropic"), set())

    def test_only_evaluation_runs_are_skipped(self):
        done = {(1, 4201), (1, 4191)}
        self.assertEqual(to_run(range(1, 3), [4201, 4191], done, {4201}), [(1, 4191), (2, 4201), (2, 4191)])

    def test_discard_moves_runs_and_comments_and_keeps_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fixtures").symlink_to(ROOT / "fixtures")
            runs = root / "runs"
            runs.mkdir()
            self.write_run(runs, "keep", critique="off")
            self.write_run(runs, "drop")
            (runs / "_ledger.jsonl").write_text('{"run_id": "drop", "total_tokens": 10}\n')
            tracker = Tracker(root, flaky=False)
            tracker.post_comment("drop", 4201, "label: bug\nfile: x")
            tracker.post_comment("keep", 4201, "label: bug\nfile: y")
            (runs / "drop.calls.jsonl").write_text("{}\n")
            self.assertEqual(discard("planned", [4201], critique="self", root=root, log=lambda *_: None), 1)
            self.assertEqual(sorted(p.name for p in runs.glob("*.jsonl")), ["_ledger.jsonl", "keep.jsonl"])
            self.assertTrue((runs / "discarded" / "drop.jsonl").exists())
            self.assertTrue((runs / "discarded" / "drop.calls.jsonl").exists())
            self.assertEqual([c["run_id"] for c in tracker.table("comments")], ["keep"])
            self.assertIn('"drop"', (runs / "discarded" / "tracker_rows.jsonl").read_text())


class ScriptedPlannerTests(unittest.TestCase):
    """The scripted models write plans in whatever schema the planner's tool offers."""

    SCHEMA = {"type": "object", "additionalProperties": False, "required": ["steps"], "properties": {"steps": {
        "type": "array", "items": {"type": "object", "additionalProperties": False,
                                   "required": ["id", "action", "tool", "args_json", "depends_on",
                                                "expected_result", "status", "note"],
                                   "properties": {"id": {"type": "string"}, "action": {"type": "string"},
                                                  "tool": {"type": ["string", "null"]},
                                                  "args_json": {"type": "string"},
                                                  "depends_on": {"type": "array", "items": {"type": "string"}},
                                                  "expected_result": {"type": "string"},
                                                  "status": {"type": "string", "enum": ["pending", "done"]},
                                                  "note": {"type": ["string", "null"]}}}}}}
    TOOL = {"name": "submit_plan", "description": "d", "input_schema": SCHEMA}

    def test_a_plan_in_the_offered_schema(self):
        content, stop, _, _ = RecordingPlanner().create(
            system="s", messages=[{"role": "user", "content": "Plan issue #4192."}], tools=[self.TOOL])
        self.assertEqual(stop, "tool_use")
        steps = content[0]["input"]["steps"]
        self.assertEqual([s["id"] for s in steps], ["1", "2", "3", "4", "5"])
        self.assertEqual(steps[3]["depends_on"], ["1", "3"])
        self.assertEqual(steps[3]["tool"], tool_for("open_pr"))
        self.assertEqual(steps[4]["tool"], tool_for("comment"))
        self.assertEqual(json.loads(steps[0]["args_json"]), role_call("read_issue", number=4192)[1])
        self.assertIsNone(steps[0]["note"])
        self.assertIs(plan_tool([{"name": "read_issue", "input_schema": {"type": "object"}}, self.TOOL]), self.TOOL)

    def test_the_invalid_planner_and_the_off_plan_executor(self):
        content, _, _, _ = AlwaysInvalidPlanner().create(system="s", messages=[{"role": "user", "content": "#4191"}],
                                                       tools=[self.TOOL])
        self.assertEqual(content[0]["input"]["steps"][0]["tool"], "export_report")
        self.assertEqual(errors(content[0]["input"], self.SCHEMA), [])   # only the four checks can reject it
        self.assertEqual(content[0]["input"]["steps"][-1]["tool"], tool_for("comment"))
        executor = OffPlanExecutor()
        search = [t for t in default_tools(RunContext("r", Tracker(ROOT), ROOT)).schemas
                  if t["name"] == tool_for("search")]
        content, _, _, _ = executor.create(system="s", messages=[{"role": "user", "content": "#4192"}], tools=search)
        self.assertEqual(content[0]["name"], tool_for("comment"))
        self.assertIn(OFF_PLAN_MARK, content[0]["input"][arg("comment", "body")])

    def test_a_plan_that_passes_the_checks_and_breaks_the_schema(self):
        content, _, _, _ = SchemaBreakingPlanner().create(system="s", messages=[{"role": "user", "content": "#4191"}],
                                                          tools=[self.TOOL])
        steps = content[0]["input"]["steps"]
        self.assertTrue(all("action" not in s and "rationale" in s for s in steps))
        self.assertTrue(errors(content[0]["input"], self.SCHEMA))

    def test_a_plan_with_no_comment_and_a_search_for_the_sentinel(self):
        content, _, _, _ = NoCommentPlanner().create(system="s", messages=[{"role": "user", "content": "#4191"}],
                                                     tools=[self.TOOL])
        self.assertEqual([s["tool"] for s in content[0]["input"]["steps"]],
                         [tool_for(r) for r in ("read_issue", "search", "read_file")])
        search = [t for t in default_tools(RunContext("r", Tracker(ROOT), ROOT)).schemas
                  if t["name"] == tool_for("search")]
        issue = Tracker(ROOT).issue(4191)["body"]
        content, _, _, _ = SentinelSearcher().create(system="s", messages=[{"role": "user", "content": issue}],
                                                     tools=search)
        self.assertEqual(content[0]["input"][arg("search", "query")], "SNTL-RUST-CURLEW")

    def test_a_model_that_will_not_read(self):
        read = [t for t in default_tools(RunContext("r", Tracker(ROOT), ROOT)).schemas
                if t["name"] == tool_for("read_file")]
        content, stop, _, _ = RefusesToRead().create(system="s", messages=[{"role": "user", "content": "#4191"}],
                                                     tools=read)
        self.assertEqual((content[0]["type"], stop), ("text", "end_turn"))

    def test_a_scripted_draft_and_a_watched_file(self):
        post = [t for t in default_tools(RunContext("r", Tracker(ROOT), ROOT)).schemas
                if t["name"] == tool_for("comment")]
        content, _, _, _ = DraftNamesMissingFile().create(system="s", messages=[{"role": "user", "content": "#4192"}],
                                                          tools=post)
        self.assertEqual(content[0]["input"][arg("comment", "body")], "label: bug\nfile: src/export/tsv.ts")
        with tempfile.TemporaryDirectory() as tmp:
            watched = Path(tmp) / "p.json"
            watched.write_text('{"steps_done": [1]}')
            model = ScriptedTriage(watch=watched)
            model.create(system="s", messages=[{"role": "user", "content": 'notes: {"steps_done": [1]}'}], tools=None)
            model.create(system="s", messages=[{"role": "user", "content": "no notes"}], tools=None)
            self.assertEqual(model.shown, [True, False])


if __name__ == "__main__":
    unittest.main()


class Assignment3TrackerTests(unittest.TestCase):
    """The SQLite tracker: run-scoped reads, keys accepted once, and the two ways it lies."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def tracker(self, **kw):
        return Tracker(ROOT, state_dir=self.state, **{"flaky": False, "readback_fail": False, **kw})

    def test_every_read_is_scoped_to_one_run(self):
        t = self.tracker()
        t.post_comment("run-a", 4191, "a")
        t.open_pr("run-a", 4191, "repomind/issue-4191", "t", "b")
        self.assertEqual(t.comments("run-b"), [])
        self.assertEqual(t.prs("run-b", branch="repomind/issue-4191"), [])
        self.assertEqual(len(t.prs("run-a", branch="repomind/issue-4191")), 1)
        with self.assertRaises(TypeError):
            t.comments(None)

    def test_a_key_is_accepted_once_and_a_repeat_gets_the_first_result(self):
        t = self.tracker()
        first = t.post_comment("run-a", 4191, "a", key="k1")
        again = t.post_comment("run-a", 4191, "a changed text", key="k1")
        self.assertEqual(again["id"], first["id"])
        self.assertTrue(again["replayed"])
        self.assertEqual(len(t.comments("run-a")), 1)
        self.assertEqual([a["outcome"] for a in t.table("attempts")], ["written", "replayed"])

    def test_a_timeout_hides_whether_the_write_happened(self):
        t = self.tracker(faults=["after_commit", "before_commit"])
        for _ in range(2):
            with self.assertRaises(TrackerTimeout):
                t.post_comment("run-a", 4191, "a", key="k1")
        self.assertEqual(len(t.comments("run-a")), 1)
        self.assertEqual([a["outcome"] for a in t.table("attempts")],
                         ["timeout_after_commit", "timeout_before_commit"])
        self.assertIsNotNone(t.comment_by_key("run-a", "k1"))

    def test_readback_fails_only_for_a_run_whose_write_timed_out(self):
        t = self.tracker(faults=[None, "after_commit"], readback_fail=True)
        t.post_comment("run-b", 4191, "b")
        with self.assertRaises(TrackerTimeout):
            t.post_comment("run-a", 4191, "a", key="k1")
        with self.assertRaises(ReadbackUnavailable):
            t.comment_by_key("run-a", "k1")
        self.assertEqual(len(t.comments("run-b")), 1)

    def test_flaky_writes_time_out_about_six_times_in_ten(self):
        t = self.tracker(flaky=True, seed=7)
        outcomes = []
        for i in range(400):
            try:
                t.post_comment("run-a", 4191, str(i))
                outcomes.append("ok")
            except TrackerTimeout:
                outcomes.append("timeout")
        self.assertTrue(200 <= outcomes.count("timeout") <= 280, outcomes.count("timeout"))

    def test_reset_archives_the_database(self):
        t = self.tracker()
        t.post_comment("run-a", 4191, "a")
        archived = t.reset()
        self.assertTrue(archived.exists())
        self.assertEqual(t.table("comments"), [])


class Assignment3HarnessTests(unittest.TestCase):
    def test_the_switches_and_their_defaults(self):
        import os
        from unittest import mock
        from harness import switches
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(switches.current(), switches.DEFAULTS)
        with mock.patch.dict(os.environ, {"FLAKY_WRITES": "1", "KEY_MODE": "uuid", "VERIFY": "off"}, clear=True):
            self.assertEqual(switches.current(), {"flaky_writes": True, "readback_fail": False,
                                                  "key_mode": "uuid", "verify": "off"})
        with mock.patch.dict(os.environ, {"KEY_MODE": "random"}, clear=True):
            with self.assertRaises(SystemExit):
                switches.current()

    def test_the_call_record_refuses_what_a_checker_could_not_read(self):
        from harness.calls import CallRecord, read_calls
        with tempfile.TemporaryDirectory() as tmp:
            record = CallRecord(Path(tmp) / "r.calls.jsonl", "r")
            record.write(tool=tool_for("comment"), args={"number": 4191}, outcome="timeout", is_error=True,
                         result="the tracker did not answer", latency_s=10, key="k1", plan_step=4)
            with self.assertRaises(ValueError):
                record.write(tool="post_comment", args={}, outcome="maybe", is_error=True, result="", latency_s=0)
            line = read_calls(Path(tmp) / "r.calls.jsonl")[0]
        self.assertEqual((line["role"], line["key"], line["attempt"], line["plan_step"]), ("comment", "k1", 1, 4))

    @unittest.skipUnless(STARTER_NAMES, "describes the starter's names, which you have changed")
    def test_roles_name_the_starter_tools(self):
        from harness.roles import role_of, roles
        table = roles()
        self.assertEqual(table["search"], {"tool": "search_repo", "args": {"query": "query", "path": "filter"}})
        self.assertEqual(role_of("open_pr"), "open_pr")
        self.assertIsNone(role_of("no_such_tool"))

    def test_the_registry_sends_four_fields_only(self):
        tools = default_tools(RunContext("r", Tracker(ROOT), ROOT / "fixtures" / "repo"))
        for schema in tools.schemas:
            self.assertLessEqual(set(schema), {"name", "description", "input_schema", "strict"})
        self.assertIsInstance(tools.hooks, list)

    @unittest.skipUnless(STUB_SEARCH, "describes the starter's search stub, which you have rewritten")
    def test_the_search_stub_cannot_tell_nothing_from_malformed(self):
        tools = default_tools(RunContext("r", Tracker(ROOT), ROOT / "fixtures" / "repo"))
        for query in ("zqxwvkjh", "", "   ", "x" * 500):
            self.assertEqual(tools.call("search_repo", {"query": query}).content, "No matches.")
        self.assertEqual(tools.call("search_repo", {"query": "export", "filter": "src/[x"}).content, "No matches.")
        found = tools.call("search_repo", {"query": "SUPPORTED_FORMATS"}).content
        self.assertIn("src/exportUtils.ts:", found)
        self.assertRegex(found.splitlines()[-1], r"^\[index built 2026-09-28T09:00:00Z, .*; \d+ matches, \d+ shown\]$")

    def test_the_trace_finds_paths_in_a_json_search_result(self):
        content = json.dumps({"count": 2, "results": [{"path": "src/a.ts", "line": 1}, {"path": "./src/b.ts"}]})
        self.assertEqual(result_paths("search_repo", {}, content, False), ["src/a.ts", "src/b.ts"])

    def test_a_scripted_call_follows_the_first_example(self):
        from harness.scripted import like
        self.assertEqual(like("issue-4190", 4192), "issue-4192")
        self.assertEqual(like(4190, 4192), 4192)
        self.assertEqual(triage_steps(4192)[3]["args"][arg("open_pr", "branch")], "repomind/issue-4192")

    def test_the_two_arms_are_two_configurations(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            runs.mkdir()
            lines = [{"type": "run_start", "run_id": "a", "lab": LAB, "way": "planned", "issue": 4201, "sweep": 1,
                      "backend": "anthropic", "critique": "off", "notes": "off",
                      "switches": {"flaky_writes": True, "readback_fail": False, "key_mode": "uuid", "verify": "off"}},
                     {"type": "end", "run_id": "a", "terminal_reason": "completed"}, {"type": "run_end", "run_id": "a"}]
            (runs / "a.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
            harness_arm = {"flaky_writes": True, "readback_fail": False, "key_mode": "derived", "verify": "on"}
            control = {**harness_arm, "key_mode": "uuid", "verify": "off"}
            self.assertEqual(finished_pairs(runs, "planned", "off", "off", "anthropic", harness_arm), set())
            self.assertEqual(finished_pairs(runs, "planned", "off", "off", "anthropic", control), {(1, 4201)})

    def test_ping_hashes_the_definitions_as_sent(self):
        from harness.ping import current_schemas, definitions_hash
        schemas = current_schemas()
        self.assertEqual(definitions_hash(schemas), definitions_hash(json.loads(json.dumps(schemas))))
        self.assertNotEqual(definitions_hash(schemas), definitions_hash(schemas[:4]))
