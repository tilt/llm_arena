"""Executes model-requested tool calls: validation, permission policy, tracing, error capture.

Every failure mode becomes a string result for the model *and* a classified span attribute
(`error_kind`) for the evaluators — invalid-argument and unknown-tool rates are step metrics.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from llm_arena.core.trace import Trace
from llm_arena.llm.types import ToolCall
from llm_arena.tools.registry import Permission, ToolRegistry

ErrorKind = Literal["unknown_tool", "invalid_args", "forbidden", "runtime", "rejected"]  # rejected: by a human approver
MAX_RESULT_CHARS = 6000


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    ok: bool
    error_kind: ErrorKind | None = None
    value: Any = None


class Executor(Protocol):
    """What a tool loop needs: the offered tools and a way to run a call (ToolExecutor, or a gated wrapper)."""

    registry: ToolRegistry

    async def execute(self, call: ToolCall) -> ToolOutcome: ...


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        trace: Trace,
        *,
        allowed_permissions: frozenset[Permission] = frozenset({"read", "write", "destructive"}),
        role: str | None = None,
    ) -> None:
        self.registry = registry
        self.trace = trace
        self.allowed_permissions = allowed_permissions
        self.role = role

    async def execute(self, call: ToolCall) -> ToolOutcome:
        with self.trace.span("tool_call", call.name, role=self.role, input=call.args) as span:
            outcome = await self._run(call)
            span.output = outcome.content
            span.attrs.update({"ok": outcome.ok, "error_kind": outcome.error_kind, "raw_args": call.raw_args})
            if item := self.registry.get(call.name):
                span.attrs["permission"] = item.permission
            return outcome

    async def _run(self, call: ToolCall) -> ToolOutcome:
        item = self.registry.get(call.name)
        if item is None:
            available = ", ".join(self.registry.names())
            return ToolOutcome(f"Error: unknown tool {call.name!r}. Available: {available}", False, "unknown_tool")
        if item.permission not in self.allowed_permissions:
            return ToolOutcome(f"Error: tool {call.name!r} is not permitted in this context.", False, "forbidden")
        try:
            params = item.params_model.model_validate(call.args)
        except ValidationError as exc:
            return ToolOutcome(f"Error: invalid arguments for {call.name}: {_short(exc)}", False, "invalid_args")
        try:
            value = item.fn(**params.model_dump())
            if inspect.isawaitable(value):
                value = await value
        except Exception as exc:  # tool failures are observations for the model, not crashes
            return ToolOutcome(f"Error: {call.name} failed: {exc}", False, "runtime")
        return ToolOutcome(render_result(value), True, None, value)


def render_result(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + f"\n…[truncated {len(text) - MAX_RESULT_CHARS} chars]"
    return text


def _short(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'args'}: {err['msg']}" for err in exc.errors()[:5])
