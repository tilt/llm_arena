"""Model specifications: everything needed to call one model, independent of the arena."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["openai", "anthropic", "ollama", "lmstudio", "openai_compatible"]
# auto: the official SDK of the provider on the server (openai / anthropic); http: the transport-agnostic
# ProtocolClient (always used in the browser); aisuite: the aisuite library.
Backend = Literal["auto", "openai", "anthropic", "http", "aisuite"]
ToolMode = Literal["native", "json"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]  # none: thinking off


class Capabilities(BaseModel):
    """What a model can do; checked before a run so a bad role binding fails fast."""

    model_config = ConfigDict(frozen=True)

    tools: bool = True
    vision: bool = False
    json_schema: bool = True  # server honours response_format={"type": "json_schema"}
    reasoning: bool = False


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Arena-wide alias, e.g. 'qwen3-14b@lmstudio'")
    provider: Provider
    model: str = Field(description="Model id as the server knows it")
    base_url: str | None = None
    api_key_env: str | None = None
    backend: Backend = "auto"
    # json: the model answers {"tool": ..., "args": ...} instead of using native tool calls —
    # a fallback for local models whose native tool calling is unreliable.
    tool_mode: ToolMode = "native"
    temperature: float | None = 0.2
    reasoning_effort: ReasoningEffort | None = None
    max_tokens: int | None = None
    # Cold local models regularly need minutes for the first token; 120 s proved too short.
    timeout_s: float = 300.0
    max_retries: int = 3
    concurrency: int | None = None
    capabilities: Capabilities = Field(default_factory=Capabilities)
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.provider in ("ollama", "lmstudio")

    def with_overrides(self, **overrides: Any) -> ModelSpec:
        return self.model_copy(update=overrides)
