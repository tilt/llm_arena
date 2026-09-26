"""OpenAI-compatible servers (OpenAI, Ollama /v1, LM Studio, vLLM) via the official openai SDK.

Request and response mapping is the shared pure `openai_chat` mapper; the SDK only transports and
retries, so this client and the browser's fetch client produce identical requests.
"""

from __future__ import annotations

import time
from typing import Any

import openai
from openai import AsyncOpenAI
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from llm_arena.llm.cache import ResponseCache
from llm_arena.llm.errors import ProviderError
from llm_arena.llm.limits import limiter_for
from llm_arena.llm.protocols import openai_chat
from llm_arena.llm.registry import resolve_api_key, resolve_base_url
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import parse_json_tool_reply
from llm_arena.llm.types import LLMResponse, Message

_TRANSIENT = (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError)


def is_transient(exc: BaseException) -> bool:
    """Worth retrying? An exhausted quota also arrives as HTTP 429 but will not recover by waiting."""
    if not isinstance(exc, _TRANSIENT):
        return False
    body = getattr(exc, "body", None)
    code = body.get("code") if isinstance(body, dict) else None
    return code != "insufficient_quota" and "insufficient_quota" not in str(exc)


class OpenAIChatClient:
    def __init__(self, spec: ModelSpec, *, sdk_client: AsyncOpenAI | None = None, cache: ResponseCache | None = None):
        self.spec = spec
        self._sdk = sdk_client or AsyncOpenAI(
            base_url=resolve_base_url(spec),
            api_key=resolve_api_key(spec),
            timeout=spec.timeout_s,
            max_retries=0,  # tenacity owns retries so they are counted in one place
        )
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
        body = openai_chat.build_request(
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
            completion = await self._create_with_retries(body)
            latency = time.perf_counter() - started
        response = openai_chat.parse_response(completion.model_dump(), self.spec, latency)
        if tools and self.spec.tool_mode == "json":
            response = parse_json_tool_reply(response)
        if self._cache and cache_key:
            self._cache.put(cache_key, response)
        return response

    async def _create_with_retries(self, body: dict[str, Any]) -> Any:
        # Server-specific extras (e.g. Ollama options) are not SDK parameters: pass them through extra_body.
        extra = {key: body.pop(key) for key in list(body) if key in self.spec.extra_body}
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(is_transient),
                stop=stop_after_attempt(self.spec.max_retries + 1),
                wait=wait_random_exponential(multiplier=1, max=30),
                reraise=True,
            ):
                with attempt:
                    return await self._sdk.chat.completions.create(**body, extra_body=extra or None)
        except openai.OpenAIError as exc:
            raise ProviderError(f"{self.spec.name}: {type(exc).__name__}: {exc}") from exc
        raise ProviderError(f"{self.spec.name}: no attempt was made")  # unreachable; keeps mypy honest
