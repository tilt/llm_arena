"""Opt-in integration tests against real model servers: `pytest -m live` (or `make test-live`).

Set ARENA_LIVE_MODELS to a comma-separated list of aliases/refs, e.g.
  ARENA_LIVE_MODELS="lmstudio:qwen/qwen3-14b,gpt-4.1-mini" uv run pytest -m live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_arena.adapters.server.clients import get_client
from llm_arena.llm.probe import probe_model
from llm_arena.llm.registry import load_model_specs, resolve_model

pytestmark = pytest.mark.live

MODELS = [m.strip() for m in os.getenv("ARENA_LIVE_MODELS", "").split(",") if m.strip()]
SPECS = load_model_specs(Path(__file__).resolve().parents[1] / "configs" / "models.yaml")


@pytest.mark.skipif(not MODELS, reason="set ARENA_LIVE_MODELS")
@pytest.mark.parametrize("ref", MODELS)
async def test_model_answers_and_calls_tools(ref: str) -> None:
    spec = resolve_model(ref, SPECS)
    result = await probe_model(spec, get_client(spec))
    assert result.reachable, result.errors
    assert result.chat_ok, result.errors
