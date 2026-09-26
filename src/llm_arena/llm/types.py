"""Provider-neutral message and response types. No I/O, no arena imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Messages stay in the OpenAI chat format: every backend we target (OpenAI, Ollama /v1,
# LM Studio, aisuite) speaks it, so a richer wrapper would only add conversion code.
Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None  # OpenAI-style servers need the call id echoed in the tool result
    raw_args: str | None = None  # the unparsed argument string, kept for argument-validity evals


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.latency_s + other.latency_s,
            self.cost_usd + other.cost_usd,
        )


@dataclass
class LLMResponse:
    """One model turn: either tool calls or a final text answer (content)."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str | None = None
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw_message: Message = field(default_factory=dict)  # assistant message to append to history
    finish_reason: str | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)
