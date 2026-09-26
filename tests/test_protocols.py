"""The transport-agnostic client and both protocol mappers, against a fake transport."""

from __future__ import annotations

from typing import Any

import pytest

from llm_arena.llm.errors import ProviderError
from llm_arena.llm.http_client import ProtocolClient
from llm_arena.llm.protocols import anthropic_messages
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import tool_result_message
from llm_arena.llm.transport import HttpResponse, TransportError
from llm_arena.llm.types import ToolCall

ADD = {"type": "function", "function": {"name": "add", "description": "Add.", "parameters": {"type": "object"}}}
CLAUDE = ModelSpec(name="anthropic:claude-haiku-4-5", provider="anthropic", model="claude-haiku-4-5", max_retries=2)
OPUS = ModelSpec(name="anthropic:claude-opus-5", provider="anthropic", model="claude-opus-5", reasoning_effort="low")


class FakeTransport:
    def __init__(self, *responses: HttpResponse | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def post_json(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
    ) -> HttpResponse:
        self.requests.append((url, headers, body))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _claude_reply(*blocks: dict[str, Any], stop: str = "end_turn") -> HttpResponse:
    usage = {"input_tokens": 1000, "output_tokens": 200}
    return HttpResponse(
        200, {"content": list(blocks), "usage": usage, "stop_reason": stop, "model": "claude-haiku-4-5"}
    )


def test_anthropic_request_mapping() -> None:
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": [{"type": "text", "text": "chart?"},
                                      {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "add", "arguments": '{"a": 1}'}},
            {"id": "t2", "type": "function", "function": {"name": "add", "arguments": '{"a": 2}'}}]},
        tool_result_message("native", ToolCall("add", {}, id="t1"), "1"),
        tool_result_message("native", ToolCall("add", {}, id="t2"), "2"),
    ]  # fmt: skip
    body = anthropic_messages.build_request(CLAUDE, messages, tools=[ADD], temperature=0.0)
    assert body["system"] == "Be brief." and body["max_tokens"] == 16000 and body["temperature"] == 0.0
    assert body["tools"] == [{"name": "add", "description": "Add.", "input_schema": {"type": "object"}}]
    user, assistant, results = body["messages"]
    assert user["content"][1]["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}
    assert [b["input"] for b in assistant["content"]] == [{"a": 1}, {"a": 2}]
    # Parallel tool results travel in ONE user message.
    assert [b["tool_use_id"] for b in results["content"]] == ["t1", "t2"]


def test_current_claude_models_get_no_temperature_but_effort() -> None:
    body = anthropic_messages.build_request(OPUS, [{"role": "user", "content": "hi"}], temperature=0.5)
    assert "temperature" not in body and body["output_config"] == {"effort": "low"}


async def test_claude_turn_round_trip_keeps_original_blocks() -> None:
    thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
    transport = FakeTransport(
        _claude_reply(thinking, {"type": "tool_use", "id": "t1", "name": "add", "input": {"a": 1}}, stop="tool_use"),
        _claude_reply({"type": "text", "text": "done"}),
    )
    client = ProtocolClient(CLAUDE, transport, api_key="k", browser=True)
    first = await client.complete([{"role": "user", "content": "add"}], tools=[ADD])
    assert first.tool_calls[0].args == {"a": 1} and first.finish_reason == "tool_use"
    assert first.usage.cost_usd == pytest.approx((1000 * 1.0 + 200 * 5.0) / 1e6)
    history = [
        {"role": "user", "content": "add"},
        first.raw_message,
        tool_result_message("native", first.tool_calls[0], "1"),
    ]
    second = await client.complete(history, tools=[ADD])
    assert second.content == "done"
    _, headers, body = transport.requests[1]
    assert headers["anthropic-dangerous-direct-browser-access"] == "true" and headers["x-api-key"] == "k"
    assert body["messages"][1]["content"][0] == thinking  # replayed unchanged, signature included


async def test_retries_transient_errors_but_not_billing() -> None:
    overloaded = HttpResponse(529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    transport = FakeTransport(TransportError("reset"), overloaded, _claude_reply({"type": "text", "text": "ok"}))
    assert (
        await ProtocolClient(CLAUDE, transport, api_key="k", backoff_s=lambda attempt: 0).complete(
            [{"role": "user", "content": "x"}]
        )
    ).content == "ok"
    billing = HttpResponse(400, {"type": "error", "error": {"type": "billing_error", "message": "no credit"}})
    transport = FakeTransport(billing)
    with pytest.raises(ProviderError, match="billing_error"):
        await ProtocolClient(CLAUDE, transport, api_key="k", backoff_s=lambda attempt: 0).complete(
            [{"role": "user", "content": "x"}]
        )
    assert len(transport.requests) == 1


async def test_openai_protocol_client_quota_is_permanent() -> None:
    spec = ModelSpec(name="openai:gpt-4.1-mini", provider="openai", model="gpt-4.1-mini")
    quota = HttpResponse(429, {"error": {"code": "insufficient_quota", "message": "no credits"}})
    transport = FakeTransport(quota)
    with pytest.raises(ProviderError, match="no credits"):
        await ProtocolClient(spec, transport, api_key="k").complete([{"role": "user", "content": "x"}])
    url, headers, body = transport.requests[0]
    assert url == "https://api.openai.com/v1/chat/completions" and headers["Authorization"] == "Bearer k"
    assert len(transport.requests) == 1
