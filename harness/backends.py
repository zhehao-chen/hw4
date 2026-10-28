"""Model backends. A backend turns one request into (content, stop_reason, model, usage).

Two real backends, so you can use any vendor's model that supports tool calling:

- AnthropicBackend: Claude, through Anthropic's own API.
- OpenAICompatibleBackend: any OpenAI-compatible chat completions API: OpenAI,
  Google Gemini, Mistral, DeepSeek, Groq, OpenRouter, a local Ollama or vLLM
  server, and many more. Set `base_url` in settings.yaml to your provider's.

The harness keeps every message in one format, whatever the vendor: content
blocks (text, tool_use, tool_result), as harness/client.py describes. The
OpenAI-compatible backend translates to and from its wire format, so your code
never changes when you change vendor.

Scripted backends for testing live in harness/scripted.py. `make_backend` picks
one by name; a dotted "module:Class" name loads any other class with the same
create() method.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import time

from harness.client import Usage

REAL_BACKENDS = {"anthropic", "openai-compatible"}   # the ones that call a real model

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicBackend:
    """Claude through the official SDK. Credentials come from the environment:
    ANTHROPIC_API_KEY, or a profile from `ant auth login`. Tool definitions go
    out as they are, so a tool marked "strict": true asks for strict tool use. A
    rate limit (429) or an overload (529) is waited out as long as Anthropic asks,
    the same way as for the OpenAI-compatible backend (with_retries)."""

    name = "anthropic"

    def __init__(self, settings):
        import anthropic  # imported here so scripted runs need no SDK

        self.settings = settings
        key = os.environ.get(settings.api_key_env) if settings.api_key_env else None
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

    def create(self, *, system, messages, tools):
        s = self.settings
        params = {"model": s.model, "max_tokens": s.max_tokens, "messages": messages}
        if system:
            params["system"] = system
        if tools:
            params["tools"] = tools
        if s.effort:
            params["output_config"] = {"effort": s.effort}
        def send():
            if s.fallbacks:
                return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks=s.fallbacks, **params)
            return self.client.messages.create(**params)

        response = with_retries(send)   # 429, 529 and "overloaded": wait as long as Anthropic asks
        content = [block.to_dict(exclude_none=True) for block in response.content]
        return content, response.stop_reason, response.model, _usage(response.usage)


def _usage(u) -> Usage:
    creation = getattr(u, "cache_creation", None)
    write_1h = getattr(creation, "ephemeral_1h_input_tokens", 0) if creation else 0
    return Usage(
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_creation_1h_tokens=write_1h or 0,
    )


# -- OpenAI-compatible APIs --------------------------------------------------------

_STOP_REASONS = {"tool_calls": "tool_use", "function_call": "tool_use", "stop": "end_turn",
                 "length": "max_tokens", "content_filter": "refusal"}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if b.get("type") == "text")


def to_openai_messages(system: str | None, messages: list[dict]) -> list[dict]:
    """The harness's messages, as chat completions messages."""
    out = [{"role": "system", "content": system}] if system else []
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            turn = {"role": "assistant", "content": _text_of(content) or None}
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                      **(b.get("vendor_extra") or {})}
                     for b in content if b.get("type") == "tool_use"]
            if calls:
                turn["tool_calls"] = calls
            out.append(turn)
            continue
        # A user turn: tool results become "tool" messages, which must come first,
        # straight after the assistant turn that asked for them.
        for b in content:
            if b.get("type") == "tool_result":
                text = _text_of(b.get("content"))
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                            "content": f"Error: {text}" if b.get("is_error") and not text.startswith("Error") else text})
        text = _text_of(content)
        if text:
            out.append({"role": "user", "content": text})
    return out


def to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
    """The harness's tool definitions in function form. A definition marked
    "strict": true goes out as function.strict, so a vendor with a strict mode
    compiles its schema; one without it decides for itself what to do with it."""
    if not tools:
        return None
    out = []
    for t in tools:
        function = {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}
        if t.get("strict") is not None:
            function["strict"] = bool(t["strict"])
        out.append({"type": "function", "function": function})
    return out


def from_openai_response(data: dict, requested_model: str):
    """A chat completions response (as a dict) as (content, stop_reason, model, usage)."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_unparsed_arguments": fn.get("arguments")}
        block = {"type": "tool_use", "id": call.get("id") or f"call_{i}",
                 "name": fn.get("name", ""), "input": args if isinstance(args, dict) else {"value": args}}
        # Anything else on the call belongs to the vendor and must go back unchanged.
        # Some vendors refuse the next call without it (Gemini's thought_signature).
        extra = {k: v for k, v in call.items() if k not in ("id", "type", "function", "index") and v is not None}
        if extra:
            block["vendor_extra"] = extra
        content.append(block)
    finish = choice.get("finish_reason") or "stop"
    stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in content) else _STOP_REASONS.get(finish, finish)
    u = data.get("usage") or {}
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    prompt = u.get("prompt_tokens") or 0
    usage = Usage(input_tokens=max(0, prompt - cached), output_tokens=u.get("completion_tokens") or 0,
                  cache_read_input_tokens=cached)
    return content, stop_reason, data.get("model") or requested_model, usage


RATE_LIMIT_RETRIES = 6      # a free tier's per-minute limit clears within a minute
MAX_WAIT_S = 90.0

# A per-day quota does not clear in a minute: retrying only stalls every call. Gemini's
# refusal names its quota metric (GenerateRequestsPerDayPerProjectPerModel-FreeTier);
# other vendors say "per day", "daily" or "RPD".
DAILY_QUOTA = re.compile(r"per[\s_-]*day|perday|daily|\brpd\b|requests[\s_-]*per[\s_-]*day", re.IGNORECASE)


class DailyQuotaReached(RuntimeError):
    """The vendor's daily quota is spent. The runner ends the run (terminal reason
    quota), stops the sweep, and a later run of the same command picks up from there."""


class RateLimited(RuntimeError):
    """The vendor still refused after every retry. The runner ends the run
    (terminal reason rate_limited), which never counts as finished, so running the
    same command again redoes it."""


def is_retryable(error: Exception) -> bool:
    """A refusal worth waiting out: a rate limit (429), Anthropic's overload (529),
    or any refusal that says the model is overloaded."""
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    name = type(error).__name__
    return (status in (429, 529) or "RateLimit" in name or "Overloaded" in name
            or "overloaded" in str(error).lower())


def with_retries(call, *, retryable=is_retryable, sleep=None):
    """call(), retried after a retryable refusal for as long as the vendor asks
    (retry_delay), up to RATE_LIMIT_RETRIES times. A per-day quota raises
    DailyQuotaReached at once; a refusal that outlasts the retries, RateLimited."""
    sleep = sleep or time.sleep
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return call()
        except Exception as exc:
            if not retryable(exc):
                raise
            if is_daily_quota(exc):
                raise DailyQuotaReached(str(exc)[:300]) from exc
            if attempt == RATE_LIMIT_RETRIES:
                raise RateLimited(f"still refused after {RATE_LIMIT_RETRIES} retries: {str(exc)[:200]}") from exc
            sleep(retry_delay(exc, attempt))


def is_daily_quota(error: Exception) -> bool:
    """Whether a refusal is a per-day quota, from its message or its response body."""
    response = getattr(error, "response", None)
    body = ""
    try:
        body = response.text if response is not None else ""
    except Exception:  # an unread or streamed body: the message is enough
        body = ""
    return bool(DAILY_QUOTA.search(f"{error} {getattr(error, 'body', '') or ''} {body}"))


def retry_delay(error: Exception, attempt: int) -> float:
    """How long to wait after a rate-limit refusal: the standard Retry-After header
    when the vendor sends one, else a figure in its message ("retry in 36.2s",
    "retryDelay": "36s"), else a growing guess."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    after = headers.get("retry-after") if hasattr(headers, "get") else None
    if after:
        try:
            return min(float(after) + 1, MAX_WAIT_S)
        except ValueError:
            pass
    found = re.search(r"retry in ([\d.]+)\s*s|retryDelay['\"]?:\s*['\"]([\d.]+)s", str(error))
    seconds = float(found.group(1) or found.group(2)) + 1 if found else 5.0 * 2 ** attempt
    return min(seconds, MAX_WAIT_S)


class OpenAICompatibleBackend:
    """Any model behind an OpenAI-compatible chat completions API.

    settings.yaml: provider openai-compatible, model as your provider names it,
    base_url your provider's endpoint (none for OpenAI itself), and api_key_env
    the environment variable holding your key (default OPENAI_API_KEY)."""

    name = "openai-compatible"

    def __init__(self, settings):
        import openai  # imported here so scripted runs need no SDK

        self.settings = settings
        env = settings.api_key_env or "OPENAI_API_KEY"
        key = os.environ.get(env)
        if not key:
            raise RuntimeError(f"no API key: set the environment variable {env} "
                               "(settings.yaml's api_key_env names it)")
        self.client = openai.OpenAI(api_key=key, base_url=settings.base_url or None)
        self.rate_limited = openai.RateLimitError
        # OpenAI's own API wants max_completion_tokens; most other providers take max_tokens.
        official = not settings.base_url or "api.openai.com" in settings.base_url
        self.max_field = "max_completion_tokens" if official else "max_tokens"

    def create(self, *, system, messages, tools):
        s = self.settings
        params = {"model": s.model, "messages": to_openai_messages(system, messages),
                  self.max_field: s.max_tokens}
        if tools:
            params["tools"] = to_openai_tools(tools)
        # Free tiers allow only a few calls a minute, and so many a day (with_retries).
        response = with_retries(lambda: self.client.chat.completions.create(**params),
                                retryable=lambda e: isinstance(e, self.rate_limited) or is_retryable(e))
        return from_openai_response(response.model_dump(), s.model)


def make_backend(name: str, settings):
    if name == "anthropic":
        return AnthropicBackend(settings)
    if name == "openai-compatible":
        return OpenAICompatibleBackend(settings)
    if name == "never-stops":
        from harness.scripted import NeverStops
        return NeverStops()
    if ":" in name:
        module, cls = name.split(":", 1)
        return getattr(importlib.import_module(module), cls)(settings)
    raise ValueError(f"unknown backend {name!r}: use anthropic, openai-compatible, never-stops, or module:Class")
