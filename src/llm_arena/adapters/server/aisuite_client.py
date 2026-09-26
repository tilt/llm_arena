"""Backend via aisuite ("provider:model" strings) — optional extra `llm-arena[aisuite]`.

aisuite's client is synchronous, so calls run in a worker thread. Tools are passed as JSON
schemas (aisuite's manual mode); the arena's own tool loop executes them, which keeps tool
execution traced and permission-checked the same way for every backend.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from llm_arena.llm.errors import ProviderError
from llm_arena.llm.limits import limiter_for
from llm_arena.llm.protocols.openai_chat import parse_response
from llm_arena.llm.reasoning import sampling_params
from llm_arena.llm.registry import resolve_api_key, resolve_base_url
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import parse_json_tool_reply, wire_messages, with_json_tool_instructions
from llm_arena.llm.types import LLMResponse, Message


class AisuiteClient:
    def __init__(self, spec: ModelSpec) -> None:
        try:
            import aisuite
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ProviderError("aisuite backend needs the extra: uv sync --extra aisuite") from exc
        self.spec = spec
        self._model_ref, provider_configs = _aisuite_target(spec)
        self._client = aisuite.Client(provider_configs=provider_configs)

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = sampling_params(self.spec, temperature)
        if tools and self.spec.tool_mode == "json":
            messages = with_json_tool_instructions(messages, tools)
        elif tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format
        if max_tokens or self.spec.max_tokens:
            kwargs["max_tokens"] = max_tokens or self.spec.max_tokens

        async with limiter_for(self.spec):
            started = time.perf_counter()
            try:
                completion = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self._model_ref,
                    messages=wire_messages(messages),
                    **kwargs,
                )
            except Exception as exc:  # aisuite re-raises provider-specific exception types
                raise ProviderError(f"{self.spec.name} via aisuite: {exc}") from exc
            latency = time.perf_counter() - started

        response = parse_response(_as_dict(completion), self.spec, latency)
        return parse_json_tool_reply(response) if tools and self.spec.tool_mode == "json" else response


def _aisuite_target(spec: ModelSpec) -> tuple[str, dict[str, dict[str, Any]]]:
    """Map our provider to an aisuite model string plus provider config.

    aisuite >= 0.2 ships `ollama` and `lmstudio` providers that take the server root as
    `api_url` (they append /v1 themselves); generic servers use its OpenAI provider.
    """
    if spec.provider in ("ollama", "lmstudio"):
        root = (resolve_base_url(spec) or "").removesuffix("/").removesuffix("/v1")
        config: dict[str, Any] = {"timeout": spec.timeout_s, **({"api_url": root} if root else {})}
        return f"{spec.provider}:{spec.model}", {spec.provider: config}
    config = {"api_key": resolve_api_key(spec), "timeout": spec.timeout_s}
    if spec.provider != "openai":
        config["base_url"] = resolve_base_url(spec)
    return f"openai:{spec.model}", {"openai": config}


def _as_dict(value: Any) -> Any:
    """aisuite returns OpenAI SDK objects for some providers and its own classes for others."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list | tuple):
        return [_as_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _as_dict(item) for key, item in value.items()}
    if hasattr(value, "__dict__"):
        return {key: _as_dict(item) for key, item in vars(value).items() if not key.startswith("_")}
    return value
