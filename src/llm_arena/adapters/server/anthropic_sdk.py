"""Claude via the official `anthropic` SDK (extra `anthropic`).

Message conversion and response parsing are the shared pure `anthropic_messages` mapper (the
browser engine uses the same mapper over fetch), so both runtimes send identical requests.
"""

from __future__ import annotations

import time
from typing import Any

from llm_arena.llm.cache import ResponseCache
from llm_arena.llm.errors import ProviderError
from llm_arena.llm.limits import limiter_for
from llm_arena.llm.protocols import anthropic_messages
from llm_arena.llm.registry import resolve_api_key
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import parse_json_tool_reply
from llm_arena.llm.types import LLMResponse, Message


class AnthropicSDKClient:
    def __init__(self, spec: ModelSpec, *, sdk_client: Any = None, cache: ResponseCache | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ProviderError("Claude models need the extra: uv sync --extra anthropic") from exc
        self._anthropic = anthropic
        self.spec = spec
        options: dict[str, Any] = {
            "api_key": resolve_api_key(spec),
            "timeout": spec.timeout_s,
            "max_retries": spec.max_retries,
        }
        if spec.base_url:  # the SDK wants the server root, not .../v1
            options["base_url"] = spec.base_url.rstrip("/").removesuffix("/v1")
        self._sdk = sdk_client or anthropic.AsyncAnthropic(**options)
        self._cache = cache

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body = anthropic_messages.build_request(
            self.spec,
            messages,
            tools=tools,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        cache_key = self._cache.key(body) if self._cache else None
        if self._cache and cache_key and (cached := self._cache.get(cache_key)):
            return cached
        extra = {key: body.pop(key) for key in list(body) if key in self.spec.extra_body}
        async with limiter_for(self.spec):
            started = time.perf_counter()
            try:
                message = await self._sdk.messages.create(**body, extra_body=extra or None)
            except self._anthropic.APIError as exc:  # SDK already retried 408/409/429/5xx and connection errors
                raise ProviderError(f"{self.spec.name}: {type(exc).__name__}: {exc}") from exc
            latency = time.perf_counter() - started
        response = anthropic_messages.parse_response(message.to_dict(), self.spec, latency)
        if tools and self.spec.tool_mode == "json":
            response = parse_json_tool_reply(response)
        if self._cache and cache_key:
            self._cache.put(cache_key, response)
        return response
