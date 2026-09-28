"""Role → model bindings for one trial, with every call recorded in the trial's trace.

A pipeline asks for `roles["critic"]`, never for a concrete model: that indirection is what
lets one pipeline run under many model configurations.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from llm_arena.core.errors import ConfigError
from llm_arena.core.trace import Span, Trace
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.types import LLMResponse, Message


class TracedLLM:
    """An LLMClient that records each call as an `llm_call` span tagged with its role."""

    def __init__(self, client: LLMClient, trace: Trace, role: str) -> None:
        self._client = client
        self.trace = trace
        self.role = role

    @property
    def spec(self) -> ModelSpec:
        return self._client.spec

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        with self.trace.span("llm_call", self.role, role=self.role, model=self.spec.name) as span:
            span.input = self._keep_images(span, messages)
            span.attrs["n_tools"] = len(tools or [])
            response = await self._client.complete(
                messages, tools=tools, response_format=response_format, temperature=temperature, max_tokens=max_tokens
            )
            span.output = response.content
            span.prompt_tokens = response.usage.prompt_tokens
            span.completion_tokens = response.usage.completion_tokens
            span.cost_usd = response.usage.cost_usd
            span.attrs.update(
                {
                    "tool_calls": [{"name": call.name, "args": call.args} for call in response.tool_calls],
                    "reasoning_chars": len(response.reasoning or ""),
                    "finish_reason": response.finish_reason,
                    "model_latency_s": response.usage.latency_s,
                }
            )
            return response

    def _keep_images(self, span: Span, messages: list[Message]) -> list[Message]:
        """Keep traces small: each inline image becomes an artifact of the span, referenced as artifact:<key>."""
        kept: list[Message] = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                parts = []
                for part in content:
                    decoded = _data_url(part["image_url"]["url"]) if part.get("type") == "image_url" else None
                    if decoded is None:
                        parts.append(part)
                        continue
                    data, media = decoded
                    extension = media.split("/")[-1].split("+")[0]
                    ref = self.trace.attach(span, f"input-image.{extension}", data, media)
                    parts.append({"type": "image_url", "image_url": {"url": f"artifact:{ref.key or ref.name}"}})
                message = {**message, "content": parts}
            kept.append(message)
        return kept


class RoleModels:
    def __init__(self, clients: dict[str, LLMClient], trace: Trace) -> None:
        self._clients = clients
        self.trace = trace

    def __getitem__(self, role: str) -> TracedLLM:
        if role not in self._clients:
            raise ConfigError(f"no model bound to role {role!r}; bound roles: {sorted(self._clients)}")
        return TracedLLM(self._clients[role], self.trace, role)

    def get(self, role: str, fallback: str) -> TracedLLM:
        """Optional roles fall back to another role (e.g. critic defaults to the generator)."""
        return self[role] if role in self._clients else TracedLLM(self._clients[fallback], self.trace, role)

    def __contains__(self, role: object) -> bool:
        return role in self._clients


def _data_url(url: str) -> tuple[bytes, str] | None:
    match = re.fullmatch(r"data:([\w/+.-]+);base64,(.*)", url, flags=re.DOTALL)
    if not match:
        return None
    try:
        return base64.b64decode(match.group(2)), match.group(1)
    except ValueError:
        return None
