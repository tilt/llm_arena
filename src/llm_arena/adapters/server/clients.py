"""Server-side client factory: pick the backend for a ModelSpec.

`backend: auto` uses the provider's official SDK (openai / anthropic); `http` uses the same
transport-agnostic ProtocolClient the browser engine runs; `aisuite` goes through aisuite.
"""

from __future__ import annotations

import os

from llm_arena.adapters.server.disk_cache import DiskCache
from llm_arena.adapters.server.httpx_transport import HttpxTransport
from llm_arena.llm.cache import ResponseCache
from llm_arena.llm.client import LLMClient
from llm_arena.llm.http_client import ProtocolClient
from llm_arena.llm.registry import check_key_transport
from llm_arena.llm.spec import ModelSpec


def default_cache() -> ResponseCache | None:
    directory = os.getenv("ARENA_CACHE_DIR")
    return DiskCache(directory) if directory else None


def get_client(spec: ModelSpec, *, cache: ResponseCache | None = None, api_key: str | None = None) -> LLMClient:
    """`api_key` overrides the key from the environment (a named endpoint's session key in the app)."""
    check_key_transport(spec, api_key)
    cache = cache or default_cache()
    backend = spec.backend
    if backend == "auto":
        backend = "anthropic" if spec.provider == "anthropic" else "openai"
    if backend == "http":
        return ProtocolClient(spec, HttpxTransport(), api_key=api_key, cache=cache)
    if backend == "anthropic":
        from llm_arena.adapters.server.anthropic_sdk import AnthropicSDKClient

        return AnthropicSDKClient(spec, cache=cache)
    if backend == "aisuite":
        from llm_arena.adapters.server.aisuite_client import AisuiteClient

        return AisuiteClient(spec)
    from llm_arena.adapters.server.openai_sdk import OpenAIChatClient

    return OpenAIChatClient(spec, cache=cache, api_key=api_key)
