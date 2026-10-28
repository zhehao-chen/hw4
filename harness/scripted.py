"""Scripted models: test your code without spending a token.

NeverStops asks for a tool on every call and never ends its turn, so the only
thing that can stop a run is your loop's bounds. You can run your agent against it:

    python run.py --way agent --backend never-stops --set dev --runs 1

Assignment 2 adds scripted models. The checker uses them (checks/FORMATS.md,
section 10.9), and you can run any of them yourself, free:

    python run.py --way planned --backend harness.scripted:AlwaysInvalidPlanner --set dev
    python run.py --way planned --backend harness.scripted:OffPlanExecutor --set dev
    python run.py --way planned --critique external --backend harness.scripted:DraftNamesMissingFile --set dev

AlwaysInvalidPlanner   every plan it writes fits a strict schema and fails the four checks.
NoCommentPlanner       every plan it writes passes the four checks but does not end
                       with post_comment: run, it would post nothing.
SchemaBreakingPlanner  every plan it writes passes the four checks but breaks your
                       schema: each step lacks "action" and carries a property the
                       schema does not have, as a vendor that accepts "strict" and
                       does not enforce it can return.
OffPlanExecutor        writes a valid plan, then, whenever your executor asks it to
                       fill in a step, calls a tool that is not that step's tool.
RecordingPlanner       writes a valid plan and keeps a copy of every request it is
                       sent; set .mode = "revise" and it rewrites the plan's first step.
ScriptedTriage         writes a valid plan and fills it in: it searches for
                       "dedupeKey", reads src/ingest/dedupe.ts, and drafts a comment
                       naming DRAFT_PATH, every time it is asked to (a rewrite too).
                       It accepts in a self critique. Offered no tool, it answers
                       with the draft comment when the request mentions "rewrite",
                       "draft" or "comment", and "yes" otherwise. It keeps every
                       request, and, given a file to watch, whether each request
                       showed that file's text.
RefusesToRead          ScriptedTriage that will not fill in a read: asked for a path,
                       it answers that it has none, so the run ends early.
SentinelSearcher       ScriptedTriage that searches for the issue's own sentinel, as a
                       model copying text from the issue would: the search finds
                       nothing, so the checkpoint revises.
DraftNamesSeenFile     ScriptedTriage drafting src/ingest/dedupe.ts, which the run saw.
DraftNamesUnseenFile   drafting src/util/money.ts, which exists but the run never saw.
DraftNamesMissingFile  drafting src/export/tsv.ts, which does not exist.
DraftNamesNoFile       drafting "label: bug" with "file: none": the label and the file disagree.

They write plans in your own schema: they read the input_schema of the tool your
planner offers and fill in the fields checks/FORMATS.md, section 10.1, names (id,
action, tool, args or args_json, depends_on, expected_result, status), giving any
other field its type's empty value. An argument filled in at run time is "$fill".

Assignment 3. Every scripted model now finds your tools by role (tools/roles.yaml),
whatever you have renamed them, and writes each call as your tool's first example
does, with the role's arguments set (an issue number as 4192 or as "issue-4192",
whichever your example uses). Its triage plan has five steps: read the issue,
search, read a file, open a draft PR from repomind/issue-<n> (title and body
"$fill"), and post the comment, last. One model is new:

UnknownToolCaller      for the agent's loop: its first reply calls repo_delete_branch,
                       a tool no registry has; after that it ends its turn. It keeps
                       every request, so the checker can read what your loop sent
                       back (checks/FORMATS.md, section 11.7).

Token counts from scripted models are estimates: one token per four characters
of the request's JSON. They are not the real model's counts, which is fine for
testing and not fine for anything you report. Scripted runs cost nothing, do not
count toward lab_token_ceiling, and are left out of the checker's results.
"""

from __future__ import annotations

import copy
import json
import math
import re
import time

from harness import ROOT
from harness.client import Usage
from harness.formats import FILL, SENTINEL

# NeverStops' output per call, in estimated tokens (its tool call).
NEVER_STOPS_OUTPUT_TOKENS = 30

# The stub tool result the checker gives NeverStops: 1,600 characters.
STUB_RESULT = ("stub result " * 134)[:1600]

# What OffPlanExecutor writes into every off-plan call, so that a call which ran
# can be found in the trace and the tracker.
OFF_PLAN_MARK = "off-plan-probe"


def estimate_tokens(obj) -> int:
    return math.ceil(len(json.dumps(obj, sort_keys=True, default=str)) / 4)


def _input_for(tool: dict) -> dict:
    props = (tool.get("input_schema") or {}).get("properties", {})
    if "query" in props:
        return {"query": "export"}
    if "number" in props:
        return {"number": 4191}
    return {}


class NeverStops:
    """Always calls the first tool it is offered. Optional delay per call, in seconds."""

    name = "never-stops"

    def __init__(self, settings=None, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls = 0

    def create(self, *, system, messages, tools):
        if self.delay_s:
            time.sleep(self.delay_s)
        self.calls += 1
        prompt = estimate_tokens({"system": system, "tools": tools, "messages": messages})
        if tools:
            block = {"type": "tool_use", "id": f"toolu_scripted_{self.calls:04d}",
                     "name": tools[0]["name"], "input": _input_for(tools[0])}
            return [block], "tool_use", "never-stops", Usage(prompt, NEVER_STOPS_OUTPUT_TOKENS)
        # Offered no tools, it has nothing to ask for and says so.
        return ([{"type": "text", "text": "I would call a tool, but none was offered."}],
                "end_turn", "never-stops", Usage(prompt, NEVER_STOPS_OUTPUT_TOKENS))


# -- Assignment 3: your tools, found by role --------------------------------------------

_LAB2_ROLES = {
    "read_issue": ("read_issue", {"number": "number"}),
    "search": ("search_repo", {"query": "query", "path": "filter"}),
    "read_file": ("read_file", {"path": "path"}),
    "comment": ("post_comment", {"number": "number", "body": "body"}),
    "open_pr": ("open_pr", {"number": "number", "branch": "branch", "title": "title", "body": "body"}),
}
UNKNOWN_TOOL = "repo_delete_branch"


def _roles() -> dict:
    try:
        from harness.roles import roles
        return roles()
    except Exception:  # no roles file: Assignment 2's names
        return {role: {"tool": tool, "args": args} for role, (tool, args) in _LAB2_ROLES.items()}


def typical_input(tool_name: str, root=None) -> dict:
    """The input of the first example in that tool's definition file, or {}."""
    for path in sorted(((root or ROOT) / "tools").glob("*.json")):
        try:
            definition = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(definition, dict) and definition.get("name") == tool_name:
            examples = definition.get("examples") or []
            first = examples[0] if examples and isinstance(examples[0], dict) else {}
            return copy.deepcopy(first.get("input")) if isinstance(first.get("input"), dict) else {}
    return {}


def like(example_value, value):
    """`value` written as the example writes it: an issue number as 4192, or as "issue-4192"."""
    if isinstance(value, int) and not isinstance(value, bool) and isinstance(example_value, str) \
            and re.search(r"\d+", example_value):
        return re.sub(r"\d+", str(value), example_value, count=1)
    return value


def role_call(role: str, **values) -> tuple[str, dict]:
    """(your tool's name, its arguments) for one role: the tool's first example, with the
    role's arguments (checks/FORMATS.md, section 11.2) set to `values`; "$fill" stays."""
    entry = _roles()[role]
    args = typical_input(entry["tool"])
    for role_arg, value in values.items():
        name = entry["args"][role_arg]
        args[name] = value if value == FILL else like(args.get(name), value)
    return entry["tool"], args


def tool_name(role: str) -> str:
    return _roles()[role]["tool"]


# -- Assignment 2: plans in your schema ------------------------------------------------

def triage_steps(issue: int) -> list[dict]:
    """A valid five-step triage plan, in the canonical fields, with your tools' names."""
    steps = [
        ("read the issue", role_call("read_issue", number=issue), [], "the issue's title and body"),
        ("search the code for what the issue describes", role_call("search", query=FILL), [1],
         "at least one matching path"),
        ("read the file the search points to", role_call("read_file", path=FILL), [2], "the file's text"),
        ("open a draft pull request for the file the triage names",
         role_call("open_pr", number=issue, branch=f"repomind/issue-{issue}", title=FILL, body=FILL), [1, 3],
         "one open draft PR from the issue's branch"),
        ("post the triage comment", role_call("comment", number=issue, body=FILL), [1, 3, 4],
         "one comment whose first two lines are label: and file:"),
    ]
    return [{"id": i, "action": action, "tool": tool, "args": args, "depends_on": deps,
             "expected_result": expected, "status": "pending"}
            for i, (action, (tool, args), deps, expected) in enumerate(steps, 1)]


def invalid_steps(issue: int) -> list[dict]:
    """A plan that fits a strict schema, every field a value of its type, and ends with
    post_comment, so only the four checks can reject it: its first step names a tool
    that does not exist (check 1), depends on a later step (check 2) and expects
    nothing (an empty expected_result, check 3)."""
    return [
        {"id": 1, "action": "export the report", "tool": "export_report", "args": {"format": "csv"},
         "depends_on": [2], "expected_result": "", "status": "pending"},
        {"id": 2, "action": "search the code", "tool": tool_name("search"), "args": role_call("search", query=FILL)[1],
         "depends_on": [], "expected_result": "at least one matching path", "status": "pending"},
        {"id": 3, "action": "post the triage comment", "tool": tool_name("comment"),
         "args": role_call("comment", number=issue, body=FILL)[1], "depends_on": [1],
         "expected_result": "one comment whose first two lines are label: and file:", "status": "pending"},
    ]


def _resolve(schema, root):
    """Follow local references ("#/$defs/step") to the schema they name."""
    for _ in range(20):
        if not (isinstance(schema, dict) and "$ref" in schema):
            break
        node = root
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema = node
    return schema if isinstance(schema, dict) else {}


def _types(schema) -> list[str]:
    t = schema.get("type")
    if isinstance(t, list):
        return t
    if t:
        return [t]
    if "properties" in schema:
        return ["object"]
    if "items" in schema:
        return ["array"]
    return []


def _branches(schema) -> list:
    return schema.get("oneOf") or schema.get("anyOf") or []


def steps_property(schema, root=None) -> str | None:
    """The name of a plan schema's list of steps: its first array-of-objects property."""
    root = root if root is not None else schema
    schema = _resolve(schema, root)
    for name, prop in (schema.get("properties") or {}).items():
        prop = _resolve(prop, root)
        if "array" in _types(prop):
            items = _resolve(prop.get("items") or {}, root)
            if "object" in _types(items) or _branches(items):
                return name
    return None


def plan_tool(tools) -> dict | None:
    """The tool a planner or reviser offers: the one whose input holds a list of steps."""
    for tool in tools or []:
        if steps_property(tool.get("input_schema") or {}) is not None:
            return tool
    return None


def _default(schema, root):
    schema = _resolve(schema, root)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if _branches(schema):
        return _default(_branches(schema)[0], root)
    types = _types(schema)
    if "null" in types:
        return None
    first = types[0] if types else "string"
    if first == "object":
        return {name: _default(prop, root) for name, prop in (schema.get("properties") or {}).items()}
    return {"string": "", "integer": 0, "number": 0, "boolean": False, "array": []}.get(first)


def _cast(value, schema, root):
    """A value in the schema's scalar type, where it converts."""
    schema = _resolve(schema, root)
    types = _types(schema)
    if value is None or isinstance(value, (dict, list)):
        return value
    if "integer" in types and not isinstance(value, int) and "string" not in types:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if "string" in types and not isinstance(value, str) and "integer" not in types:
        return str(value)
    return value


def _branch_score(branch, tool, args, root) -> int:
    props = branch.get("properties") or {}
    score = 0
    for name, prop in props.items():
        prop = _resolve(prop, root)
        allowed = [prop["const"]] if "const" in prop else list(prop.get("enum") or [])
        if tool in allowed:
            score += 100
        elif allowed and name in ("tool", "name", "kind", "type"):
            score -= 100
    score += 10 * len(set(props) & set(args))
    score -= len(set(branch.get("required") or []) - set(args) - {"tool", "name", "kind", "type"})
    return score


def _args_value(schema, tool, args, root):
    schema = _resolve(schema, root)
    if _branches(schema):
        best = max(_branches(schema), key=lambda b: _branch_score(_resolve(b, root), tool, args, root))
        return _args_value(best, tool, args, root)
    types = _types(schema)
    if "string" in types and "object" not in types:
        return json.dumps(args)
    props = schema.get("properties") or {}
    if not props:
        return dict(args)
    out = {}
    for name, prop in props.items():
        if name in args:
            out[name] = _cast(args[name], prop, root)
        elif name in ("tool", "name"):
            out[name] = tool
        else:
            out[name] = _default(prop, root)
    return out


def _step(schema, step: dict, root) -> dict:
    schema = _resolve(schema, root)
    if _branches(schema) and not schema.get("properties"):
        schema = _resolve(_branches(schema)[0], root)
    props = schema.get("properties") or {}
    if not props:
        return copy.deepcopy(step)
    out = {}
    for name, prop in props.items():
        if name == "id":
            out[name] = _cast(step["id"], prop, root)
        elif name == "depends_on":
            items = _resolve(prop, root).get("items") or {}
            out[name] = [_cast(d, items, root) for d in step["depends_on"]]
        elif name == "args":
            out[name] = _args_value(prop, step["tool"], step["args"], root)
        elif name == "args_json":
            out[name] = json.dumps(step["args"])
        elif name in ("action", "tool", "expected_result"):
            out[name] = step[name]
        elif name == "status":
            allowed = _resolve(prop, root).get("enum")
            out[name] = "pending" if not allowed or "pending" in allowed else allowed[0]
        else:
            out[name] = _default(prop, root)
    return out


def plan_instance(schema: dict, steps: list[dict]) -> dict:
    """The plan `steps` (canonical fields), written as an instance of a plan tool's input_schema."""
    root = schema
    schema = _resolve(schema, root)
    key = steps_property(schema, root)
    items = _resolve((_resolve(schema["properties"][key], root)).get("items") or {}, root)
    out = {}
    for name, prop in (schema.get("properties") or {}).items():
        out[name] = [_step(items, s, root) for s in steps] if name == key else _default(prop, root)
    return out


def request_issue(system, messages) -> int:
    """The issue number a request names: '#4192', or else the first four-digit number."""
    text = json.dumps({"system": system, "messages": messages})
    match = re.search(r"#(\d+)\b", text) or re.search(r"\b(\d{4})\b", text)
    return int(match.group(1)) if match else 0


class _ScriptedPlanner:
    """Shared by the three scripted models of Assignment 2."""

    name = "scripted"

    def __init__(self, settings=None):
        self.calls = 0
        self.plan_calls = 0

    def _usage(self, system, messages, tools, output=60) -> Usage:
        return Usage(estimate_tokens({"system": system, "tools": tools, "messages": messages}), output)

    def _block(self, name: str, tool_input: dict) -> dict:
        return {"type": "tool_use", "id": f"toolu_{self.name}_{self.calls:04d}", "name": name, "input": tool_input}

    def _plan_reply(self, system, messages, tools, steps):
        """Answer a planner or reviser: through its plan tool, or as JSON text if it offers none."""
        self.plan_calls += 1
        tool = plan_tool(tools)
        if tool is not None:
            block = self._block(tool["name"], plan_instance(tool["input_schema"], steps))
            return [block], "tool_use", self.name, self._usage(system, messages, tools, 200)
        return ([{"type": "text", "text": json.dumps({"steps": steps})}], "end_turn", self.name,
                self._usage(system, messages, tools, 200))

    def create(self, *, system, messages, tools):
        raise NotImplementedError


class AlwaysInvalidPlanner(_ScriptedPlanner):
    """Every plan it writes fails the validator: an unknown tool, a step that depends
    on a later one, and a step with no tool and no expected result."""

    name = "always-invalid-planner"

    def create(self, *, system, messages, tools):
        self.calls += 1
        if plan_tool(tools) is not None or not tools:
            return self._plan_reply(system, messages, tools, invalid_steps(request_issue(system, messages)))
        return ([{"type": "text", "text": "I only write plans."}], "end_turn", self.name,
                self._usage(system, messages, tools, 10))


class SchemaBreakingPlanner(_ScriptedPlanner):
    """Writes the valid triage plan, then breaks the schema in each step: no "action",
    and an extra property, "rationale". The four checks pass; a schema check does not."""

    name = "schema-breaking-planner"

    def create(self, *, system, messages, tools):
        self.calls += 1
        content, stop, model, usage = self._plan_reply(system, messages, tools,
                                                       triage_steps(request_issue(system, messages)))
        if content and content[0].get("type") == "tool_use":
            tool = plan_tool(tools)
            key = steps_property(tool["input_schema"])
            for step in content[0]["input"].get(key) or []:
                if isinstance(step, dict):
                    step.pop("action", None)
                    step["rationale"] = "added by a model that was not held to the schema"
        return content, stop, model, usage


class NoCommentPlanner(_ScriptedPlanner):
    """Writes the triage plan without its last step: read, search, read, and no comment."""

    name = "no-comment-planner"

    def create(self, *, system, messages, tools):
        self.calls += 1
        return self._plan_reply(system, messages, tools, triage_steps(request_issue(system, messages))[:3])


class UnknownToolCaller(_ScriptedPlanner):
    """For the agent's loop. Its first reply calls UNKNOWN_TOOL, which no registry has;
    every later reply ends the turn. It keeps every request in .requests."""

    name = "unknown-tool-caller"

    def __init__(self, settings=None):
        super().__init__(settings)
        self.requests: list[dict] = []

    def create(self, *, system, messages, tools):
        self.calls += 1
        self.requests.append(json.loads(json.dumps({"system": system, "messages": messages, "tools": tools},
                                                   default=str)))
        if self.calls == 1:
            block = {"type": "tool_use", "id": "toolu_unknown_0001", "name": UNKNOWN_TOOL, "input": {"branch": "main"}}
            return [block], "tool_use", self.name, self._usage(system, messages, tools, 30)
        return [{"type": "text", "text": "Done."}], "end_turn", self.name, self._usage(system, messages, tools, 5)


class OffPlanExecutor(_ScriptedPlanner):
    """Writes a valid plan. Asked to fill in a step, it calls another tool: post_comment,
    unless that is the only tool offered, and then search_repo. Every off-plan call
    carries OFF_PLAN_MARK, and .off_plan_calls keeps them."""

    name = "off-plan-executor"

    def __init__(self, settings=None):
        super().__init__(settings)
        self.off_plan_calls: list[dict] = []

    def create(self, *, system, messages, tools):
        self.calls += 1
        issue = request_issue(system, messages)
        if plan_tool(tools) is not None or not tools:
            return self._plan_reply(system, messages, tools, triage_steps(issue))
        offered = [t["name"] for t in tools]
        if offered == [tool_name("comment")]:
            name, tool_input = role_call("search", query=OFF_PLAN_MARK)
        else:
            name, tool_input = role_call("comment", number=issue, body=f"label: bug\nfile: none\n\n{OFF_PLAN_MARK}")
        self.off_plan_calls.append({"name": name, "input": tool_input, "offered": offered})
        return [self._block(name, tool_input)], "tool_use", self.name, self._usage(system, messages, tools, 40)


class RecordingPlanner(_ScriptedPlanner):
    """Writes a valid plan and keeps a copy of every request in .requests.

    With .mode = "revise" it answers as a reviser that ignores its instructions: it
    rewrites the first step (as if it had not run) and the second."""

    name = "recording-planner"

    def __init__(self, settings=None, mode: str = "plan"):
        super().__init__(settings)
        self.mode = mode
        self.requests: list[dict] = []

    def create(self, *, system, messages, tools):
        self.calls += 1
        self.requests.append(json.loads(json.dumps({"system": system, "messages": messages, "tools": tools},
                                                   default=str)))
        issue = request_issue(system, messages)
        steps = triage_steps(issue)
        if self.mode == "revise":
            steps[0]["action"] = "read the issue again, rewritten by the reviser"
            steps[0]["expected_result"] = "a different result"
            steps[1]["action"] = "search again, with other terms"
        if plan_tool(tools) is not None or not tools:
            return self._plan_reply(system, messages, tools, steps)
        return ([{"type": "text", "text": "I only write plans."}], "end_turn", self.name,
                self._usage(system, messages, tools, 10))


class ScriptedTriage(_ScriptedPlanner):
    """A model that plays the planned way's calls the same way every time (see the module's docstring)."""

    name = "scripted-triage"
    QUERY = "dedupeKey"
    READ_PATH = "src/ingest/dedupe.ts"
    DRAFT_PATH = "src/ingest/dedupe.ts"

    def __init__(self, settings=None, watch=None):
        super().__init__(settings)
        self.requests: list[dict] = []
        self.watch = watch          # a progress file: record whether each request shows its text
        self.shown: list[bool] = []  # one entry per request made while the watched file existed

    def _strings(self, node) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            return [s for v in node.values() for s in self._strings(v)]
        if isinstance(node, list):
            return [s for v in node for s in self._strings(v)]
        return []

    def create(self, *, system, messages, tools):
        self.calls += 1
        request = json.loads(json.dumps({"system": system, "messages": messages, "tools": tools}, default=str))
        self.requests.append(request)
        if self.watch is not None and self.watch.exists():
            text = self.watch.read_text().strip()
            self.shown.append(bool(text) and text in "\n".join(self._strings({"s": system, "m": messages})))
        issue = request_issue(system, messages)
        if plan_tool(tools) is not None:
            return self._plan_reply(system, messages, tools, triage_steps(issue))
        for tool in tools or []:
            verdict = _verdict_input(tool)
            if verdict is not None:     # a self critique offered as a tool
                return [self._block(tool["name"], verdict)], "tool_use", self.name, self._usage(system, messages, tools)
        body = f"label: bug\nfile: {self.DRAFT_PATH}"
        if tools:
            name = tools[0]["name"]
            fills = {"search": {"query": self.query(request)}, "read_file": {"path": self.READ_PATH},
                     "comment": {"number": issue, "body": body}, "read_issue": {"number": issue},
                     "open_pr": {"number": issue, "branch": f"repomind/issue-{issue}", "title": f"Fix for issue {issue}",
                                 "body": f"Proposed change in {self.DRAFT_PATH}: the cause the triage names."}}
            role = next((r for r, e in _roles().items() if e["tool"] == name), None)
            tool_input = role_call(role, **fills[role])[1] if role else {}
            return [self._block(name, tool_input)], "tool_use", self.name, self._usage(system, messages, tools)
        text = body if re.search(r"rewrite|draft|comment", json.dumps(messages), re.IGNORECASE) else "yes"
        return [{"type": "text", "text": text}], "end_turn", self.name, self._usage(system, messages, tools)

    def query(self, request: dict) -> str:
        return self.QUERY


class RefusesToRead(ScriptedTriage):
    """Will not fill in a read_file step, as a model with no path it trusts may not:
    the executor cannot run that step, and the run ends before its comment."""

    name = "refuses-to-read"

    def create(self, *, system, messages, tools):
        if tools and [t["name"] for t in tools] == [tool_name("read_file")]:
            self.calls += 1
            self.requests.append(json.loads(json.dumps({"system": system, "messages": messages, "tools": tools},
                                                       default=str)))
            return ([{"type": "text", "text": "I have no path I trust to read."}], "end_turn", self.name,
                    self._usage(system, messages, tools, 10))
        return super().create(system=system, messages=messages, tools=tools)


class SentinelSearcher(ScriptedTriage):
    """Searches for the sentinel in the issue it was shown, as a model copying the issue's text would."""

    name = "sentinel-searcher"

    def query(self, request: dict) -> str:
        found = SENTINEL.search("\n".join(self._strings(request)))
        return found.group(1) if found else self.QUERY


def _verdict_input(tool: dict) -> dict | None:
    """An instance for a tool with an accept/revise choice, choosing accept; else None."""
    props = (tool.get("input_schema") or {}).get("properties") or {}
    choice = next((k for k, v in props.items() if "accept" in (v.get("enum") or [])), None)
    if choice is None:
        return None
    return {k: ("accept" if k == choice else None) for k in props}


class DraftNamesSeenFile(ScriptedTriage):
    name = "draft-names-seen-file"
    DRAFT_PATH = "src/ingest/dedupe.ts"


class DraftNamesUnseenFile(ScriptedTriage):
    name = "draft-names-unseen-file"
    DRAFT_PATH = "src/util/money.ts"


class DraftNamesMissingFile(ScriptedTriage):
    name = "draft-names-missing-file"
    DRAFT_PATH = "src/export/tsv.ts"


class DraftNamesNoFile(ScriptedTriage):
    name = "draft-names-no-file"
    DRAFT_PATH = "none"
