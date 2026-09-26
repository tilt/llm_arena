from __future__ import annotations

import json

import httpx
import pytest

from llm_arena.adapters.server.discovery import discover
from llm_arena.llm.pricing import known_price
from llm_arena.llm.registry import resolve_model


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/tags":
        return httpx.Response(200, json={"models": [
            {"name": "qwen3:14b", "size": 9.3e9, "details": {"parameter_size": "14.8B", "quantization_level": "Q4_K_M"}},
            {"name": "gemma3:12b", "size": 8.1e9, "details": {}},
            {"name": "nomic-embed-text", "size": 3e8, "details": {}},
        ]})  # fmt: skip
    if path == "/api/show":
        name = json.loads(request.content)["model"]
        capabilities = {"qwen3:14b": ["completion", "tools", "thinking"], "gemma3:12b": ["completion", "vision"],
                        "nomic-embed-text": ["embedding"]}[name]  # fmt: skip
        return httpx.Response(200, json={"capabilities": capabilities, "details": {"parameter_size": "12.2B"},
                                         "model_info": {"gemma3.context_length": 131072}})  # fmt: skip
    if path == "/api/ps":
        return httpx.Response(200, json={"models": [{"name": "qwen3:14b"}]})
    if request.url.port == 1234:
        raise httpx.ConnectError("connection refused")
    if path == "/v1/models":
        ids = ["gpt-4.1-mini", "gpt-4.1-mini-2025-04-14", "gpt-5-pro", "whisper-1", "gpt-4o-realtime-preview"]
        return httpx.Response(200, json={"data": [{"id": i} for i in ids]})
    return httpx.Response(404)


async def test_discovery_maps_capabilities_prices_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    catalog = await discover(transport=httpx.MockTransport(_handler))
    refs = [entry.ref for entry in catalog.entries]
    assert "ollama:nomic-embed-text" not in refs and "openai:whisper-1" not in refs
    qwen, gemma = catalog.get("ollama:qwen3:14b"), catalog.get("ollama:gemma3:12b")
    assert qwen and qwen.loaded and qwen.spec.capabilities.reasoning and qwen.spec.tool_mode == "native"
    assert gemma and gemma.spec.tool_mode == "json" and gemma.spec.capabilities.vision
    assert gemma.parameters == "12.2B" and gemma.context_length == 131072  # from /api/show when tags lack details
    assert "lmstudio" in catalog.errors
    pro = catalog.get("openai:gpt-5-pro")
    assert pro and pro.input_cost_per_mtok is None  # unknown, not guessed from the gpt-5 prefix
    assert [e.ref for e in catalog.filter(source="openai")] == ["openai:gpt-4.1-mini", "openai:gpt-5-pro"]
    assert [e.ref for e in catalog.filter(needs=frozenset({"vision"}), source="ollama")] == ["ollama:gemma3:12b"]
    assert resolve_model("ollama:gemma3:12b", {}, catalog.specs()).tool_mode == "json"


def test_snapshot_prices_map_to_family_only() -> None:
    assert known_price("gpt-4.1-mini-2025-04-14") == known_price("gpt-4.1-mini")
    assert known_price("gpt-5.4-mini") is None
