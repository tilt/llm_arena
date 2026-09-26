"""Tool-calling protocols: the provider's native API, or a JSON fallback in plain text.

The JSON mode exists because several local models (gemma, small llamas) produce broken native
tool calls. Comparing both modes on the same model is itself an interesting arena axis.
"""

from __future__ import annotations

import json
from typing import Any

from llm_arena.llm.jsonutil import extract_json
from llm_arena.llm.types import LLMResponse, Message, ToolCall

TOOL_RESULT_MARKER = "_tool_result"

_JSON_MODE_INSTRUCTION = """

## Response format
Reply with exactly one JSON object and nothing else:
- To call a tool: {{"tool": "<tool name>", "args": {{...}}}}
- To give the final answer: {{"final": "<your complete answer>"}}
Call one tool per reply. Available tools:
{tool_docs}"""


def render_tool_docs(tool_schemas: list[dict[str, Any]]) -> str:
    lines = []
    for schema in tool_schemas:
        function = schema["function"]
        parameters = function.get("parameters", {})
        required = set(parameters.get("required", []))
        params = [
            f"{name}{'' if name in required else '?'}: {spec.get('type', 'any')}"
            + (f" ({spec['description']})" if spec.get("description") else "")
            for name, spec in parameters.get("properties", {}).items()
        ]
        lines.append(f"- {function['name']}({', '.join(params)}): {function.get('description', '')}")
    return "\n".join(lines)


def with_json_tool_instructions(messages: list[Message], tool_schemas: list[dict[str, Any]]) -> list[Message]:
    """Append the JSON protocol to the system prompt (or prepend a system message)."""
    instruction = _JSON_MODE_INSTRUCTION.format(tool_docs=render_tool_docs(tool_schemas))
    if messages and messages[0].get("role") == "system":
        first = {**messages[0], "content": f"{messages[0]['content']}{instruction}"}
        return [first, *messages[1:]]
    return [{"role": "system", "content": instruction.strip()}, *messages]


def parse_json_tool_reply(response: LLMResponse) -> LLMResponse:
    """Interpret a JSON-mode reply. Unparseable output counts as a final answer.

    Treating it as final rather than retrying keeps the protocol failure visible to evaluators
    (it shows up as a wrong answer instead of being silently repaired).
    """
    try:
        data = extract_json(response.content)
    except ValueError:
        return response
    if isinstance(data, dict) and data.get("tool"):
        args = data.get("args") or {}
        call = ToolCall(
            name=str(data["tool"]),
            args=args if isinstance(args, dict) else {},
            raw_args=json.dumps(args),
        )
        response.tool_calls = [call]
        response.content = ""
        return response
    if isinstance(data, dict) and "final" in data:
        response.content = str(data.get("final") or "")
    return response


def tool_result_message(tool_mode: str, call: ToolCall, content: str) -> Message:
    """History entry carrying a tool result back to the model.

    In JSON mode the result must be a user message: OpenAI-compatible servers reject a
    role='tool' message that does not answer a native tool call id (HTTP 400).
    """
    if tool_mode == "json":
        return {"role": "user", "content": f"Result of {call.name}:\n{content}", TOOL_RESULT_MARKER: True}
    return {"role": "tool", "tool_call_id": call.id or call.name, "content": content}


def wire_messages(messages: list[Message]) -> list[Message]:
    """Strip internal marker keys (leading underscore) before sending to a provider."""
    return [{k: v for k, v in message.items() if not k.startswith("_")} for message in messages]
