"""The LLMClient protocol and backend-independent helpers built on top of it.

Concrete clients: `llm.http_client.ProtocolClient` (any runtime, injected transport) and the
server SDK clients from `llm_arena.adapters.server.clients.get_client`.

Every backend implements one method, `complete`. Chat, tool steps, structured output and
vision are thin helpers over it, so a new backend (or a test fake) gets them for free.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from llm_arena.llm.errors import StructuredOutputError
from llm_arena.llm.jsonutil import extract_json
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.types import LLMResponse, Message


@runtime_checkable
class LLMClient(Protocol):
    @property
    def spec(self) -> ModelSpec: ...

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """One model turn. With `tools`, the response may carry tool calls (native or JSON mode)."""
        ...


def system(text: str) -> Message:
    return {"role": "system", "content": text}


def user(text: str, images: list[str | Path | bytes] | None = None) -> Message:
    """A user message; with images it becomes a multi-part message for vision models."""
    if not images:
        return {"role": "user", "content": text}
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    parts.extend(image_part(image) for image in images)
    return {"role": "user", "content": parts}


def image_part(image: str | Path | bytes, mime: str = "image/png") -> dict[str, Any]:
    if isinstance(image, str) and image.startswith(("http://", "https://", "data:")):
        return {"type": "image_url", "image_url": {"url": image}}
    if isinstance(image, bytes):
        data = image
    else:
        path = Path(image)
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or mime
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


async def chat(client: LLMClient, messages: list[Message], **kwargs: Any) -> str:
    return (await client.complete(messages, **kwargs)).content


def json_schema_format(model: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": model.__name__, "schema": model.model_json_schema(), "strict": False},
    }


async def structured[T: BaseModel](
    client: LLMClient,
    messages: list[Message],
    model: type[T],
    *,
    retries: int = 2,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[T, list[LLMResponse]]:
    """Ask for output matching a pydantic model; returns the object and every raw response.

    Uses the server's json_schema mode when the spec says it is supported, and always states the
    schema in the prompt too — some local servers accept response_format but ignore it. A
    validation failure is fed back once per retry so the model can repair its own output.
    """
    schema_hint = (
        "\n\nRespond with a single JSON object that validates against this JSON schema "
        f"(no prose, no code fences):\n{model.model_json_schema()}"
    )
    conversation = [*messages[:-1], {**messages[-1], "content": _append_text(messages[-1]["content"], schema_hint)}]
    response_format = json_schema_format(model) if client.spec.capabilities.json_schema else None
    responses: list[LLMResponse] = []
    last_error = ""
    for _ in range(retries + 1):
        response = await client.complete(
            conversation, response_format=response_format, temperature=temperature, max_tokens=max_tokens
        )
        responses.append(response)
        try:
            return model.model_validate(extract_json(response.content)), responses
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:800]
            conversation = [
                *conversation,
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": f"That output was invalid: {last_error}\nReturn only the corrected JSON."},
            ]
    raise StructuredOutputError(
        f"{client.spec.name}: no valid {model.__name__} after {retries + 1} attempts: {last_error}"
    )


def _append_text(content: Any, suffix: str) -> Any:
    if isinstance(content, str):
        return content + suffix
    return [*content, {"type": "text", "text": suffix}]
