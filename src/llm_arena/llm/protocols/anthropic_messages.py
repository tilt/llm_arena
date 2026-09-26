"""Anthropic Messages API wire format: pure conversion from the arena's OpenAI-style history.

The arena keeps conversations in the OpenAI chat format everywhere; this module translates at
the edge. Used by the server adapter (official `anthropic` SDK, response via `.to_dict()`) and by
the browser engine (raw fetch — the SDK cannot run in Pyodide), so both behave identically.

Two rules that are easy to get wrong:
- Parallel tool results must come back in ONE user message (one `tool_result` block each).
- Assistant turns that came from Claude keep their original content blocks (thinking + tool_use)
  in the internal `_anthropic_content` key and are replayed unchanged, as the API expects.
"""

from __future__ import annotations

import json
import re
from typing import Any

from llm_arena.llm.pricing import cost_usd
from llm_arena.llm.reasoning import sampling_params
from llm_arena.llm.registry import resolve_base_url
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.tool_mode import with_json_tool_instructions
from llm_arena.llm.types import LLMResponse, Message, ToolCall, Usage

API_VERSION = "2023-06-01"
ORIGINAL_CONTENT_KEY = "_anthropic_content"
DEFAULT_MAX_TOKENS = 16000  # non-streaming requests: large enough not to truncate, small enough for HTTP timeouts
_DATA_URL = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)
_PERMANENT_TYPES = {
    "invalid_request_error",
    "authentication_error",
    "permission_error",
    "not_found_error",
    "billing_error",
}


def endpoint(spec: ModelSpec) -> str:
    return f"{(resolve_base_url(spec) or 'https://api.anthropic.com/v1').rstrip('/')}/messages"


def headers(api_key: str, *, browser: bool = False) -> dict[str, str]:
    result = {"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    if browser:
        # Anthropic requires this explicit opt-in before it serves CORS requests carrying a key.
        result["anthropic-dangerous-direct-browser-access"] = "true"
    return result


def build_request(
    spec: ModelSpec,
    messages: list[Message],
    *,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,  # not sent: structured() states the schema in the prompt
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    if tools and spec.tool_mode == "json":
        messages = with_json_tool_instructions(messages, tools)
    system = "\n\n".join(_text(m.get("content")) for m in messages if m.get("role") == "system")
    body: dict[str, Any] = {
        "model": spec.model,
        "max_tokens": max_tokens or spec.max_tokens or DEFAULT_MAX_TOKENS,
        "messages": convert_messages([m for m in messages if m.get("role") != "system"]),
        **sampling_params(spec, temperature),
    }
    if system:
        body["system"] = system
    if tools and spec.tool_mode == "native":
        body["tools"] = [convert_tool(tool) for tool in tools]
    body.update(spec.extra_body)
    return body


def convert_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool["function"]
    return {
        "name": function["name"],
        "description": function.get("description", ""),
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            converted.append({"role": "assistant", "content": _assistant_blocks(message)})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id"),
                "content": _text(message.get("content")),
            }
            _append_user_blocks(converted, [block])
        else:
            _append_user_blocks(converted, _user_blocks(message.get("content")))
    return converted


def parse_response(data: dict[str, Any], spec: ModelSpec, latency_s: float) -> LLMResponse:
    blocks: list[dict[str, Any]] = list(data.get("content") or [])
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    thinking = "\n".join(block.get("thinking", "") for block in blocks if block.get("type") == "thinking").strip()
    tool_calls = [
        ToolCall(
            name=block["name"],
            args=dict(block.get("input") or {}),
            id=block.get("id"),
            raw_args=json.dumps(block.get("input")),
        )
        for block in blocks
        if block.get("type") == "tool_use"
    ]
    raw: Message = {"role": "assistant", "content": text, ORIGINAL_CONTENT_KEY: blocks}
    if tool_calls:
        raw["tool_calls"] = [
            {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.raw_args}}
            for call in tool_calls
        ]
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    return LLMResponse(
        content=text,
        tool_calls=tool_calls,
        reasoning=thinking or None,
        usage=Usage(prompt_tokens, completion_tokens, latency_s, cost_usd(spec, prompt_tokens, completion_tokens)),
        model=data.get("model") or spec.model,
        raw_message=raw,
        finish_reason=data.get("stop_reason"),  # "refusal" stays visible to evaluators
    )


def error_message(data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        error = data["error"]
        return f"{error.get('type')}: {error.get('message')}"
    return str(data)[:500]


def is_permanent(status: int, data: Any) -> bool:
    error = data.get("error") if isinstance(data, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    if error_type in _PERMANENT_TYPES:
        return True
    return 400 <= status < 500 and status not in (408, 409, 429)


def _assistant_blocks(message: Message) -> list[dict[str, Any]]:
    original = message.get(ORIGINAL_CONTENT_KEY)
    if isinstance(original, list) and original:
        return original  # replay Claude's own blocks (incl. thinking) unchanged
    blocks: list[dict[str, Any]] = []
    if text := _text(message.get("content")):
        blocks.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        blocks.append({"type": "tool_use", "id": call.get("id"), "name": function.get("name"), "input": arguments})
    return blocks or [{"type": "text", "text": "(no content)"}]


def _user_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks = []
    for part in content or []:
        if part.get("type") == "text":
            blocks.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url = part["image_url"]["url"]
            match = _DATA_URL.match(url)
            source = (
                {"type": "base64", "media_type": match["mime"], "data": match["data"]}
                if match
                else {"type": "url", "url": url}
            )
            blocks.append({"type": "image", "source": source})
    return blocks


def _append_user_blocks(converted: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> None:
    """Consecutive user-side messages merge into one turn (required for parallel tool results)."""
    if converted and converted[-1]["role"] == "user":
        converted[-1]["content"].extend(blocks)
    else:
        converted.append({"role": "user", "content": list(blocks)})


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content or [] if part.get("type") == "text")
