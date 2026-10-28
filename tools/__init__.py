"""RepoMind's tools, and the registry that runs them: Assignment 3's working solution,
which ships in Assignment 4's starter in place of your own Assignment 3 code.

Each tool is two files with one name: tools/<module>.json, its definition, and
tools/<module>.py, its code. tools/roles.yaml says which tool plays each role.

Every call goes through call(), in this order:

  1. Protocol: an unknown tool is a protocol error. The full error goes to the
     harness log, the model gets GENERIC and nothing more, and a second protocol
     error in one run raises ProtocolError, which the loop ends as tool_error.
  2. The boundary (Part A, task 6): the arguments against the schema, enums compared
     case-insensitively, then the module's check(), its content rules. A rejected
     call never runs, and its error names each field and the fix.
  3. The hooks (Part C, task 5): each hook(name, args) runs before the tool; it
     allows by returning None, and denies by returning anything else or raising.
     Fail closed: a hook that raises denies.
  4. The tool. A read runs once. A write (WRITES) gets a key and the three exits:
     check before every attempt whether the effect already exists; on a timeout,
     read the write back (VERIFY=on): there, proceed; not there, retry with the
     same key; cannot tell, raise Unverifiable, and the way escalates. Never more
     than MAX_WRITE_ATTEMPTS attempts.
  5. The result against its declared shape (a module's RESULT_SCHEMA) before the
     model sees it.

Every attempt leaves one line in the call record (ctx.calls), whatever happened.
The two control switches (Part C, task 6): KEY_MODE=uuid sends a fresh random key
on every attempt; VERIFY=off skips the read-back and retries blind. The check
before every attempt stays.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from harness.schema import errors as schema_errors
from harness.tracker import ReadbackUnavailable, TrackerTimeout

TOOLS_DIR = Path(__file__).resolve().parent
MODULES = ("read_issue", "search_repo", "read_file", "post_comment", "open_pr")
SENT = ("name", "description", "input_schema", "strict")
WRITES = ("post_comment", "open_pr")
MAX_WRITE_ATTEMPTS = 3
ERROR_CHARS = 400
GENERIC = "This call could not be made."
ISSUE = re.compile(r"^issue-(\d+)$")


class ToolError(Exception):
    """A tool failed in a way the model can be told about. Becomes an is_error result."""


class ProtocolError(Exception):
    """A second protocol error in one run. The loop ends the run tool_error."""


class Unverifiable(Exception):
    """A write whose outcome the registry cannot establish: the third exit. The way escalates."""


@dataclass
class ToolResult:
    content: str
    is_error: bool
    latency_s: float
    key: str | None = None   # the idempotency key a write's last attempt carried; None for a read


@dataclass
class RunContext:
    run_id: str
    tracker: object
    repo_root: object
    calls: object = None
    harness_log: object = None
    switches: dict = field(default_factory=dict)


def issue_problem(value) -> str | None:
    if isinstance(value, str) and ISSUE.match(value.strip()):
        return None
    return (f"issue: {value!r} is not an issue identifier. Write issue- and the number, such as issue-4192.")


def issue_number(value) -> int:
    match = ISSUE.match(str(value).strip())
    if not match:
        raise ToolError(issue_problem(value))
    return int(match.group(1))


def canonical(args: dict) -> str:
    """Arguments in one standard form: keys sorted, no whitespace."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_key(run_id: str, plan_step, args: dict) -> str:
    """The idempotency key: the intended action, hashed. Never the model's to write."""
    return hashlib.sha256(f"{run_id}|{plan_step}|{canonical(args)}".encode()).hexdigest()[:24]


def render(definition: dict) -> str:
    """The description, with the examples written at its end, which every vendor reads."""
    text = definition.get("description", "")
    examples = definition.get("examples") or []
    if not examples:
        return text
    lines = [f"{i}. {json.dumps(e.get('input'))}" + (f"  ({e['note']})" if e.get("note") else "")
             for i, e in enumerate(examples, 1)]
    return text + "\n\nExamples:\n" + "\n".join(lines)


def allow_all(name: str, tool_input: dict) -> None:
    """The reference's own hook: it allows every call. What matters is where it runs."""
    return None


def load_definition(module: str) -> dict:
    return json.loads((TOOLS_DIR / f"{module}.json").read_text())


class ToolRegistry:
    def __init__(self, ctx: RunContext, modules=MODULES):
        self.ctx = ctx
        self.hooks: list = [allow_all]
        self.protocol_errors = 0
        self._tools: dict[str, tuple[str, dict, object]] = {}
        for module in modules:
            definition = load_definition(module)
            self._tools[definition["name"]] = (module, definition, importlib.import_module(f"tools.{module}"))

    @property
    def schemas(self) -> list[dict]:
        out = []
        for _, d, _ in self._tools.values():
            sent = {k: d[k] for k in SENT if k in d}
            sent["description"] = render(d)
            out.append(sent)
        return out

    def names(self) -> list[str]:
        return list(self._tools)

    def definition(self, name: str) -> dict:
        return self._tools[name][1]

    # -- the one entry point -----------------------------------------------------------
    def call(self, name: str, tool_input: dict, plan_step=None) -> ToolResult:
        start = time.monotonic()
        entry = self._tools.get(name)
        if entry is None:
            return self._protocol(name, tool_input, plan_step, start,
                                  f"unknown tool {name!r}; this registry has {self.names()}")
        module_name, definition, module = entry
        if not isinstance(tool_input, dict):
            return self._protocol(name, tool_input, plan_step, start, f"arguments are {type(tool_input).__name__}, "
                                  "not an object")
        args = self._normalize(definition, tool_input)
        problems = schema_errors(args, definition["input_schema"]) + self._content(module, args)
        if problems:
            return self._reply(name, args, plan_step, start, "rejected", True,
                               self._error(name, problems, definition))
        denied = self._denied(name, args)
        if denied:
            return self._reply(name, args, plan_step, start, "denied", True, f"This call was not allowed: {denied}")
        if module_name in WRITES:
            return self._write(name, module_name, module, args, plan_step, start)
        return self._read(name, module, args, plan_step, start)

    # -- 1. protocol errors --------------------------------------------------------------
    def _protocol(self, name, tool_input, plan_step, start, detail: str) -> ToolResult:
        self.protocol_errors += 1
        self._log(f"protocol error in {self.ctx.run_id}: {detail}; input {tool_input!r}")
        self._record(name, tool_input if isinstance(tool_input, dict) else {}, plan_step, None, 1, "protocol",
                     True, detail, start)
        if self.protocol_errors >= 2:
            raise ProtocolError(f"a second protocol error in one run: {detail}")
        return ToolResult(GENERIC, True, time.monotonic() - start)

    # -- 2. the boundary -------------------------------------------------------------------
    @staticmethod
    def _normalize(definition: dict, tool_input: dict) -> dict:
        """Enum values compared case-insensitively: "Concise" becomes "concise"."""
        props = (definition.get("input_schema") or {}).get("properties") or {}
        args = dict(tool_input)
        for key, value in args.items():
            options = (props.get(key) or {}).get("enum")
            if isinstance(value, str) and options:
                args[key] = next((o for o in options if isinstance(o, str) and o.lower() == value.lower()), value)
        return args

    @staticmethod
    def _content(module, args: dict) -> list[str]:
        check = getattr(module, "check", None)
        return check(args) if callable(check) else []

    @staticmethod
    def _error(name: str, problems: list[str], definition: dict) -> str:
        """The repair fact first: each field, what is wrong, and what would be right."""
        props = (definition.get("input_schema") or {}).get("properties") or {}
        lines = []
        for problem in problems:
            field_name = problem.split(":", 1)[0].split(".")[0].strip()
            hint = (props.get(field_name) or {}).get("description", "")
            if "required, and missing" in problem and hint:
                problem += f" It is: {hint.split('. ')[0]}."
            elif "not in the schema" in problem:
                problem += f" {name} takes only {', '.join(props)}."
            lines.append(problem)
        text = " ".join(lines) + " Fix the arguments and call again."
        return text[:ERROR_CHARS]

    # -- 3. hooks ----------------------------------------------------------------------------
    def _denied(self, name: str, args: dict) -> str | None:
        for hook in self.hooks:
            try:
                verdict = hook(name, args)
            except Exception as exc:  # fail closed
                return f"the hook {getattr(hook, '__name__', 'hook')} failed ({type(exc).__name__}), so the call is denied"
            if verdict is not None and verdict is not True:
                return str(verdict) if verdict else "denied by a hook"
        return None

    # -- 4. reads and writes -------------------------------------------------------------------
    def _read(self, name, module, args, plan_step, start) -> ToolResult:
        try:
            content = module.run(self.ctx, **args)
        except ToolError as exc:
            return self._reply(name, args, plan_step, start, "error", True, str(exc)[:ERROR_CHARS])
        shape = self._shape(module, content)
        if shape:
            self._log(f"{name} returned a result that breaks its RESULT_SCHEMA: {shape}")
            return self._reply(name, args, plan_step, start, "error", True,
                               "The tool's result did not fit its declared shape. This is a fault in RepoMind, not "
                               "in your call; retrying will not help.")
        return self._reply(name, args, plan_step, start, "ok", False, content)

    def _write(self, name, module_name, module, args, plan_step, start) -> ToolResult:
        switches = self.ctx.switches or {}
        uuid_keys = switches.get("key_mode") == "uuid"
        verify = switches.get("verify", "on") != "off"
        derived = derive_key(self.ctx.run_id, plan_step, args)
        key = uuid.uuid4().hex[:24] if uuid_keys else derived
        for attempt in range(1, MAX_WRITE_ATTEMPTS + 1):
            t0 = time.monotonic()
            try:
                existing = self._existing(module_name, args, key)   # check before every attempt
            except ReadbackUnavailable as exc:
                self._log(f"{name}: the check before attempt {attempt} could not read the tracker: {exc}")
                raise Unverifiable(f"{name}: the tracker cannot be read, so whether the write happened is unknown")
            if existing is not None:
                return self._reply(name, args, plan_step, t0, "ok", False, module.describe(existing), key=key,
                                   attempt=attempt, note="already there: ")
            try:
                content = module.run(self.ctx, idempotency_key=key, **args)
                return self._reply(name, args, plan_step, t0, "ok", False, content, key=key, attempt=attempt)
            except ToolError as exc:
                return self._reply(name, args, plan_step, t0, "error", True, str(exc)[:ERROR_CHARS], key=key,
                                   attempt=attempt)
            except TrackerTimeout as exc:
                self._record(name, args, plan_step, key, attempt, "timeout", True, str(exc), t0)
            if verify:
                try:
                    found = self._readback(module_name, key)
                except ReadbackUnavailable as exc:
                    self._log(f"{name}: attempt {attempt} timed out and the read-back failed ({exc}): escalating")
                    raise Unverifiable(f"{name} timed out, and the tracker cannot be read back to tell whether it "
                                       "happened")
                if found is not None:   # yes: it happened; proceed with the existing result
                    return self._reply(name, args, plan_step, t0, "ok", False, module.describe(found),
                                       key=key, attempt=attempt, note="verified after a timeout: ")
            if uuid_keys:               # the control's keys: a fresh one on every attempt
                key = uuid.uuid4().hex[:24]
        self._log(f"{name}: {MAX_WRITE_ATTEMPTS} attempts timed out")
        raise Unverifiable(f"{name}: {MAX_WRITE_ATTEMPTS} attempts timed out and none could be confirmed")

    def _existing(self, module_name: str, args: dict, key: str) -> dict | None:
        tracker = self.ctx.tracker
        if module_name == "open_pr":
            found = tracker.prs(self.ctx.run_id, branch=args.get("branch"))
            return found[0] if found else None
        return tracker.comment_by_key(self.ctx.run_id, key)

    def _readback(self, module_name: str, key: str) -> dict | None:
        tracker = self.ctx.tracker
        if module_name == "open_pr":
            return tracker.pr_by_key(self.ctx.run_id, key)
        return tracker.comment_by_key(self.ctx.run_id, key)

    # -- 5. results, the record, the log -------------------------------------------------------
    @staticmethod
    def _shape(module, content: str) -> list[str]:
        schema = getattr(module, "RESULT_SCHEMA", None)
        if not schema:
            return []
        try:
            return schema_errors(json.loads(content), schema)
        except ValueError:
            return ["not JSON"]

    def _reply(self, name, args, plan_step, start, outcome, is_error, content, *, key=None, attempt=1,
               note="") -> ToolResult:
        self._record(name, args, plan_step, key, attempt, outcome, is_error, note + content, start)
        return ToolResult(content, is_error, time.monotonic() - start, key)

    def _record(self, name, args, plan_step, key, attempt, outcome, is_error, result, start) -> None:
        if self.ctx.calls is not None:
            self.ctx.calls.write(tool=name, args=args, plan_step=plan_step, key=key, attempt=attempt,
                                 outcome=outcome, is_error=is_error, result=result,
                                 latency_s=max(0.0, time.monotonic() - start), cost_usd=0.0)

    def _log(self, text: str) -> None:
        if self.ctx.harness_log is not None:
            path = Path(self.ctx.harness_log)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {text}\n")


def default_tools(ctx: RunContext) -> ToolRegistry:
    return ToolRegistry(ctx)
