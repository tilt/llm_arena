"""Response caching port, so report iterations don't re-bill identical calls.

The key includes a per-trial salt (a context variable the runner sets), otherwise the repeats
that pass^k relies on would all return the first cached answer. Storage is an adapter
(`adapters.server.disk_cache.DiskCache`; the browser would use IndexedDB).
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from typing import Any, Protocol

from llm_arena.llm.types import LLMResponse

cache_salt: contextvars.ContextVar[str] = contextvars.ContextVar("cache_salt", default="")


def cache_key(payload: dict[str, Any]) -> str:
    blob = json.dumps({**payload, "_salt": cache_salt.get()}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache(Protocol):
    def key(self, payload: dict[str, Any]) -> str: ...

    def get(self, key: str) -> LLMResponse | None: ...

    def put(self, key: str, response: LLMResponse) -> None: ...
