from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from llm_arena.adapters.server.disk_cache import DiskCache
from llm_arena.adapters.server.openai_sdk import OpenAIChatClient
from llm_arena.llm.cache import cache_salt
from llm_arena.llm.client import structured, user
from llm_arena.llm.errors import StructuredOutputError
from llm_arena.llm.jsonutil import extract_json
from llm_arena.llm.pricing import cost_usd
from llm_arena.llm.protocols.openai_chat import parse_response
from llm_arena.llm.reasoning import sampling_params, split_think
from llm_arena.llm.registry import load_model_specs, parse_model_ref, resolve_base_url
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.llm.tool_mode import parse_json_tool_reply, tool_result_message, wire_messages
from llm_arena.llm.types import LLMResponse, ToolCall


def test_extract_json_handles_fences_prose_and_escaped_quotes() -> None:
    assert extract_json('Sure! ```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('The result is {"text": "he said \\"hi\\" {x}"} ok') == {"text": 'he said "hi" {x}'}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_split_think_separates_reasoning_including_unterminated_blocks() -> None:
    assert split_think("<think>plan</think>Answer") == ("Answer", "plan")
    assert split_think("Partial <think>cut off") == ("Partial", "cut off")


def test_thinking_can_be_switched_off_for_ollama_but_not_sent_to_anthropic() -> None:
    ollama = ModelSpec(name="x", provider="ollama", model="qwen3:4b", reasoning_effort="none")
    assert sampling_params(ollama)["reasoning_effort"] == "none"
    anthropic = ModelSpec(name="y", provider="anthropic", model="claude-haiku-4-5", reasoning_effort="none")
    assert "output_config" not in sampling_params(anthropic)


def test_reasoning_models_get_no_temperature() -> None:
    assert "temperature" not in sampling_params(ModelSpec(name="x", provider="openai", model="gpt-5-mini"))
    assert sampling_params(ModelSpec(name="x", provider="lmstudio", model="qwen", temperature=0.4)) == {
        "temperature": 0.4
    }


def test_json_tool_reply_becomes_tool_call_or_final() -> None:
    call = parse_json_tool_reply(LLMResponse(content='{"tool": "search", "args": {"q": "x"}}'))
    assert call.tool_calls[0].name == "search" and call.tool_calls[0].args == {"q": "x"}
    final = parse_json_tool_reply(LLMResponse(content='{"final": "done"}'))
    assert final.content == "done" and not final.tool_calls
    garbage = parse_json_tool_reply(LLMResponse(content="I think the answer is 4"))
    assert garbage.content == "I think the answer is 4"


def test_json_mode_tool_results_are_user_messages_and_markers_are_stripped() -> None:
    message = tool_result_message("json", ToolCall("search", {}), "result")
    assert message["role"] == "user"
    assert "_tool_result" not in wire_messages([message])[0]
    assert tool_result_message("native", ToolCall("s", {}, id="c1"), "r") == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "r",
    }


def test_model_refs_and_yaml_specs(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = parse_model_ref("lmstudio:qwen/qwen3-14b")
    assert spec.model == "qwen/qwen3-14b" and resolve_base_url(spec) == "http://localhost:1234/v1"
    monkeypatch.setenv("ARENA_OLLAMA_BASE_URL", "http://gpu-box:11434/v1")
    assert resolve_base_url(parse_model_ref("ollama:qwen3:8b")) == "http://gpu-box:11434/v1"
    path = tmp_path / "models.yaml"
    path.write_text("defaults: {temperature: 0.0}\nmodels:\n  m: {provider: openai, model: gpt-4.1-mini}\n")
    assert load_model_specs(path)["m"].temperature == 0.0
    with pytest.raises(ValueError):
        parse_model_ref("nope:model")


def test_cost_uses_family_prefix_and_zero_for_local() -> None:
    dated = ModelSpec(name="x", provider="openai", model="gpt-4.1-mini-2025-04-14")
    assert cost_usd(dated, 1_000_000, 0) == pytest.approx(0.40)
    assert cost_usd(ModelSpec(name="x", provider="lmstudio", model="q"), 10**6, 10**6) == 0.0


class Answer(BaseModel):
    value: int


async def test_structured_repairs_invalid_output_once() -> None:
    llm = ScriptedLLM(["not json", '{"value": 7}'])
    parsed, responses = await structured(llm, [user("give me 7")], Answer)
    assert parsed.value == 7 and len(responses) == 2
    assert "invalid" in llm.calls[1][-1]["content"]


async def test_structured_gives_up_after_retries() -> None:
    with pytest.raises(StructuredOutputError):
        await structured(ScriptedLLM(['{"value": "x"}']), [user("?")], Answer, retries=1)


def _completion_dict(content: str | None, tool_calls: list[Any] | None = None) -> dict[str, Any]:
    message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
    return {
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "model": "m",
    }


def _completion(content: str | None) -> Any:
    data = _completion_dict(content)
    return SimpleNamespace(model_dump=lambda: data)


def test_parse_completion_keeps_invalid_tool_arguments_visible() -> None:
    call = {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{broken"}}
    response = parse_response(_completion_dict("", [call]), ModelSpec(name="x", provider="lmstudio", model="m"), 0.5)
    assert response.tool_calls[0].args == {} and response.tool_calls[0].raw_args == "{broken"
    assert response.raw_message["tool_calls"][0]["id"] == "c1"


class FakeSDK:
    def __init__(self, content: str) -> None:
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content = content

    async def _create(self, **request: Any) -> Any:
        self.requests.append(request)
        return _completion(self._content)


async def test_openai_client_json_tool_mode_rewrites_request_and_parses_reply() -> None:
    sdk = FakeSDK('{"tool": "add", "args": {"a": 1, "b": 2}}')
    spec = ModelSpec(name="g", provider="lmstudio", model="gemma", tool_mode="json")
    client = OpenAIChatClient(spec, sdk_client=sdk)  # type: ignore[arg-type]
    tools = [{"type": "function", "function": {"name": "add", "description": "Add.", "parameters": {"type": "object"}}}]
    response = await client.complete([{"role": "system", "content": "sys"}, user("1+2")], tools=tools)
    request = sdk.requests[0]
    assert "tools" not in request and "add(" in request["messages"][0]["content"]
    assert response.tool_calls[0].args == {"a": 1, "b": 2}


async def test_openai_reasoning_models_use_max_completion_tokens() -> None:
    sdk = FakeSDK("ok")
    client = OpenAIChatClient(ModelSpec(name="o", provider="openai", model="o4-mini"), sdk_client=sdk)  # type: ignore[arg-type]
    await client.complete([user("hi")], max_tokens=50)
    assert sdk.requests[0]["max_completion_tokens"] == 50 and "temperature" not in sdk.requests[0]


async def test_disk_cache_is_salted_per_repeat(tmp_path: Any) -> None:
    sdk = FakeSDK("cached")
    client = OpenAIChatClient(
        ModelSpec(name="c", provider="lmstudio", model="m"), sdk_client=sdk, cache=DiskCache(tmp_path)
    )  # type: ignore[arg-type]
    await client.complete([user("hi")])
    await client.complete([user("hi")])
    assert len(sdk.requests) == 1
    token = cache_salt.set("repeat=1")
    try:
        await client.complete([user("hi")])
    finally:
        cache_salt.reset(token)
    assert len(sdk.requests) == 2


def test_exhausted_quota_is_not_retried() -> None:
    import httpx
    import openai

    from llm_arena.adapters.server.openai_sdk import is_transient

    response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    quota = openai.RateLimitError("no credits", response=response, body={"code": "insufficient_quota"})
    throttled = openai.RateLimitError("slow down", response=response, body={"code": "rate_limit_exceeded"})
    assert not is_transient(quota) and is_transient(throttled)
