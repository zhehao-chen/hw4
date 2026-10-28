"""A helper the ways share: a tool call made by code, traced."""

from harness.client import ToolCall


def code_tool(ctx, step: int, name: str, tool_input: dict) -> str:
    """A tool call made by our code rather than the model, traced like any other."""
    call = ToolCall(id=f"code-{name}-{step}", name=name, input=tool_input)
    result = ctx.tools.call(name, tool_input)
    ctx.trace.tool_call(step, call, result)
    if result.is_error:
        raise RuntimeError(f"{name} failed: {result.content}")
    return result.content
