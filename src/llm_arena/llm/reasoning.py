"""Quirks of reasoning models: sampling restrictions and where they put their thoughts."""

from __future__ import annotations

import re
from typing import Any

from llm_arena.llm.spec import ModelSpec

# OpenAI reasoning models reject any temperature other than the default.
_FIXED_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


# Claude models from Opus 4.7 / Sonnet 5 on reject sampling parameters (HTTP 400); these still accept them.
_CLAUDE_WITH_SAMPLING = (
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
)


def accepts_temperature(spec: ModelSpec) -> bool:
    if spec.provider == "openai":
        return not spec.model.startswith(_FIXED_TEMPERATURE_PREFIXES)
    if spec.provider == "anthropic":
        return spec.model.startswith(_CLAUDE_WITH_SAMPLING)
    return True


def sampling_params(spec: ModelSpec, temperature: float | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    chosen = spec.temperature if temperature is None else temperature
    if chosen is not None and accepts_temperature(spec):
        params["temperature"] = chosen
    if spec.reasoning_effort and spec.provider in ("openai", "ollama"):
        # Ollama maps it onto its think switch; "none" turns thinking off (Qwen3 answers ~10x faster).
        params["reasoning_effort"] = spec.reasoning_effort
    if spec.reasoning_effort and spec.reasoning_effort != "none" and spec.provider == "anthropic":
        # Anthropic has no "minimal"; its lowest effort level is "low".
        effort = "low" if spec.reasoning_effort == "minimal" else spec.reasoning_effort
        params["output_config"] = {"effort": effort}
    return params


def split_think(content: str) -> tuple[str, str | None]:
    """Separate inline <think>…</think> blocks (Qwen3, DeepSeek-R1 via some servers) from the answer.

    An unterminated block (generation cut off mid-thought) counts entirely as reasoning.
    """
    thoughts = [match.strip() for match in _THINK_BLOCK.findall(content)]
    answer = _THINK_BLOCK.sub("", content)
    if "<think>" in answer:
        head, _, tail = answer.partition("<think>")
        answer, thoughts = head, [*thoughts, tail.strip()]
    reasoning = "\n\n".join(t for t in thoughts if t) or None
    return answer.strip(), reasoning


def message_reasoning(message: Any) -> str | None:
    """Servers expose reasoning under different attribute names; take whichever is present."""
    for attribute in ("reasoning_content", "reasoning", "thinking"):
        value = getattr(message, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
