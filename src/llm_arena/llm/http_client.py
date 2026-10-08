"""Transport-agnostic LLM client: protocol mapper + injected ChatTransport.

This is the client the browser engine uses (with a fetch transport), and it works on the server
too (httpx transport). Retries, quota handling, JSON tool mode and caching live here once, so every
runtime gets identical behaviour; only the byte-moving transport differs.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from types import ModuleType
from typing import Any

from llm_arena.llm.cache import ResponseCache
from llm_arena.llm.errors import ProviderError
from llm_arena.llm.limits import limiter_for
from llm_arena.llm.protocols import anthropic_messages, openai_chat
from llm_arena.llm.registry import resolve_api_key
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import parse_json_tool_reply
from llm_arena.llm.transport import ChatTransport, TransportError
from llm_arena.llm.types import LLMResponse, Message


def protocol_for(spec: ModelSpec) -> ModuleType:
    return anthropic_messages if spec.provider == "anthropic" else openai_chat


class ProtocolClient:
    def __init__(
        self,
        spec: ModelSpec,
        transport: ChatTransport,
        *,
        api_key: str | None = None,
        browser: bool = False,
        cache: ResponseCache | None = None,
        backoff_s: Callable[[int], float] | None = None,
    ) -> None:
        self.spec = spec
        self._backoff_s = backoff_s or _jittered_backoff
        self._transport = transport
        self._api_key = api_key if api_key is not None else resolve_api_key(spec)
        self._browser = browser
        self._cache = cache
        self._protocol = protocol_for(spec)

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body = self._protocol.build_request(
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
        async with limiter_for(self.spec):
            started = time.perf_counter()
            data = await self._post_with_retries(body)
            latency = time.perf_counter() - started
        response: LLMResponse = self._protocol.parse_response(data, self.spec, latency)
        if tools and self.spec.tool_mode == "json":
            response = parse_json_tool_reply(response)
        if self._cache and cache_key:
            self._cache.put(cache_key, response)
        return response

    def _headers(self) -> dict[str, str]:
        if self._protocol is anthropic_messages:
            return anthropic_messages.headers(self._api_key, browser=self._browser)
        return openai_chat.headers(self._api_key)

    async def _post_with_retries(self, body: dict[str, Any]) -> dict[str, Any]:
        url, headers = self._protocol.endpoint(self.spec), self._headers()
        last_error = ""
        for attempt in range(self.spec.max_retries + 1):
            if attempt:
                await asyncio.sleep(self._backoff_s(attempt))
            try:
                response = await self._transport.post_json(url, headers, body, self.spec.timeout_s)
            except TransportError as exc:
                last_error = f"connection error: {exc}"
                continue
            if 200 <= response.status < 300:
                return dict(response.data)
            last_error = f"HTTP {response.status}: {self._protocol.error_message(response.data)}"
            if self._protocol.is_permanent(response.status, response.data):
                break
        raise ProviderError(self.spec.redact(f"{self.spec.name}: {last_error}"))


def _jittered_backoff(attempt: int) -> float:
    return min(30.0, float(2**attempt) * random.uniform(0.5, 1.0))
