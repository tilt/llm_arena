"""OpenAI Chat Completions wire format (OpenAI, Ollama /v1, LM Studio, vLLM): pure request/response mapping.

Works on plain JSON dicts so the SDK client, the httpx client and the browser fetch client all
share it; the SDK client simply passes `completion.model_dump()`.
"""

from __future__ import annotations

import json
from typing import Any

from llm_arena.llm.pricing import cost_usd
from llm_arena.llm.reasoning import sampling_params, split_think
from llm_arena.llm.registry import resolve_base_url
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import wire_messages, with_json_tool_instructions
from llm_arena.llm.types import LLMResponse, Message, ToolCall, Usage

# In JSON tool mode we ask servers that support it to constrain output to one agent step.
JSON_STEP_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_step",
        "schema": {
            "type": "object",
            "properties": {"tool": {"type": "string"}, "args": {"type": "object"}, "final": {"type": "string"}},
        },
    },
}


def endpoint(spec: ModelSpec) -> str:
    base = resolve_base_url(spec) or "https://api.openai.com/v1"
    return f"{base.rstrip('/')}/chat/completions"


def headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def build_request(
    spec: ModelSpec,
    messages: list[Message],
    *,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"model": spec.model, **sampling_params(spec, temperature)}
    if tools and spec.tool_mode == "json":
        messages = with_json_tool_instructions(messages, tools)
        if spec.capabilities.json_schema and response_format is None:
            response_format = JSON_STEP_FORMAT
    elif tools:
        body["tools"] = tools
    body["messages"] = wire_messages(messages)
    if response_format:
        body["response_format"] = response_format
    limit = max_tokens or spec.max_tokens
    if limit:
        # OpenAI reasoning models only accept max_completion_tokens; other servers want max_tokens.
        body["max_completion_tokens" if spec.provider == "openai" else "max_tokens"] = limit
    body.update(spec.extra_body)
    return body


def parse_response(data: dict[str, Any], spec: ModelSpec, latency_s: float) -> LLMResponse:
    choice = data["choices"][0]
    message = choice.get("message") or {}
    content_raw = message.get("content") or ""
    content, inline_reasoning = split_think(content_raw)
    reasoning = _reasoning(message) or inline_reasoning
    raw: Message = {"role": "assistant", "content": content_raw}
    tool_calls: list[ToolCall] = []
    if message.get("tool_calls"):
        raw["tool_calls"] = [
            {"id": call.get("id"), "type": "function", "function": call["function"]} for call in message["tool_calls"]
        ]
        tool_calls = [_tool_call(call) for call in message["tool_calls"]]
    usage_data = data.get("usage") or {}
    prompt_tokens = int(usage_data.get("prompt_tokens") or 0)
    completion_tokens = int(usage_data.get("completion_tokens") or 0)
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        reasoning=reasoning,
        usage=Usage(prompt_tokens, completion_tokens, latency_s, cost_usd(spec, prompt_tokens, completion_tokens)),
        model=data.get("model") or spec.model,
        raw_message=raw,
        finish_reason=choice.get("finish_reason"),
    )


def error_message(data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        return str(data["error"].get("message") or data["error"])
    return str(data)[:500]


def is_permanent(status: int, data: Any) -> bool:
    """HTTP errors that retrying cannot fix. An exhausted quota arrives as 429 but never recovers by waiting."""
    if status == 429:
        error = data.get("error") if isinstance(data, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        return code == "insufficient_quota" or "insufficient_quota" in str(data)
    return 400 <= status < 500 and status not in (408, 409)


def _reasoning(message: dict[str, Any]) -> str | None:
    # Servers disagree on the field name: reasoning_content (DeepSeek/vLLM), reasoning (Ollama), thinking.
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tool_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function") or {}
    raw_args = function.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except json.JSONDecodeError:
        args = {}  # invalid arguments stay visible through raw_args for the argument-validity eval
    return ToolCall(
        name=str(function.get("name")),
        args=args if isinstance(args, dict) else {},
        id=call.get("id"),
        raw_args=str(raw_args),
    )
