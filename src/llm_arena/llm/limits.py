"""Per-endpoint concurrency limits shared by every client that talks to the same server."""

from __future__ import annotations

import asyncio

from llm_arena.llm.registry import resolve_base_url, resolve_concurrency
from llm_arena.llm.spec import ModelSpec

# Keyed by event loop as well: a semaphore used from two loops raises RuntimeError, and tests
# (and the CLI) may create more than one loop per process.
_SEMAPHORES: dict[tuple[int, str, str], asyncio.Semaphore] = {}


def limiter_for(spec: ModelSpec) -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, spec.provider, resolve_base_url(spec) or "default")
    if key not in _SEMAPHORES:
        _SEMAPHORES[key] = asyncio.Semaphore(resolve_concurrency(spec))
    return _SEMAPHORES[key]
