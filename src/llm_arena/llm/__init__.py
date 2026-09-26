"""Reusable LLM client utilities (OpenAI SDK + aisuite) for OpenAI, Ollama and LM Studio.

This package is pure (no network or SDK imports) and has no dependency on the rest of llm_arena.
Concrete clients come from a runtime: on the server,

    from llm_arena.adapters.server.clients import get_client
    from llm_arena.llm import parse_model_ref, user, structured
    client = get_client(parse_model_ref("lmstudio:qwen/qwen3-14b"))
    reply = await client.complete([user("Hello")])

and in the browser, `ProtocolClient(spec, PyfetchTransport(), api_key=..., browser=True)`.
"""

from llm_arena.llm.client import LLMClient, chat, image_part, structured, system, user
from llm_arena.llm.registry import load_model_specs, parse_model_ref, resolve_model
from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.tool_mode import tool_result_message
from llm_arena.llm.types import LLMResponse, Message, ToolCall, Usage

__all__ = [
    "Capabilities",
    "LLMClient",
    "LLMResponse",
    "Message",
    "ModelSpec",
    "ToolCall",
    "Usage",
    "chat",
    "image_part",
    "load_model_specs",
    "parse_model_ref",
    "resolve_model",
    "structured",
    "system",
    "tool_result_message",
    "user",
]
