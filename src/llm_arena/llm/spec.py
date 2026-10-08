"""Model specifications: everything needed to call one model, independent of the arena."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from typing import Any, Literal, get_args
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    # The named OpenAI-compatible endpoint this model is served by (openai_compatible only): its key is bound to it.
    endpoint: str | None = None
    # Which server that name pointed to (`Endpoint.identity`): part of the setup, so a moved endpoint is a new setup.
    endpoint_identity: str | None = None
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

    def redact(self, text: str) -> str:
        """Hide a named endpoint's URL in text that may end up in traces, run bundles or exports."""
        if not self.endpoint or not self.base_url:
            return text
        host = urlsplit(self.base_url).hostname or ""
        text = text.replace(self.base_url, f"<endpoint {self.endpoint}>")
        return text.replace(host, f"<endpoint {self.endpoint}>") if host else text


def key_transport_ok(base_url: str) -> bool:
    """May a key travel to this URL? Over https always; over plain http only to this machine or a private network,
    never in cleartext across the internet."""
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return True
    host = parts.hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # a public name over http
    return address.is_loopback or address.is_private


_ENDPOINT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# An endpoint id is the prefix of its model refs ('gpu-box:qwen3'), so it must not shadow a provider or one of the
# decision-service prefixes a study candidate may use.
RESERVED_ENDPOINT_IDS = frozenset(get_args(Provider)) | {"ollaya", "jev", "typesafe", "tavily"}


class Endpoint(BaseModel):
    """A self-hosted or third-party server speaking the OpenAI chat API (vLLM, llama.cpp, LiteLLM, ...).

    Its models are discovered from `GET {base_url}/models` and referenced as '<id>:<model>'. The server lists
    no capabilities, so the endpoint states the defaults for all of its models; a curated alias can refine one.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    base_url: str = Field(description="API root including the version, e.g. 'http://203.0.113.7:8000/v1'")
    # Only set in YAML: an env key is bound to the URL written next to it, and the app drops it when the URL moves.
    api_key_env: str | None = Field(default=None, description="env var holding the key (YAML only)")
    capabilities: Capabilities = Field(default_factory=Capabilities)
    # Self-hosted models have no per-token price; a paid hosted endpoint can state one.
    input_cost_per_mtok: float = Field(default=0.0, ge=0)
    output_cost_per_mtok: float = Field(default=0.0, ge=0)
    concurrency: int | None = Field(default=None, ge=1)
    salt: str = Field(
        default_factory=lambda: secrets.token_hex(8),
        pattern=r"^[0-9a-f]{16,64}$",
        description="random, so the endpoint's identity (a keyed hash of its URL) cannot be reversed to the URL",
    )

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not _ENDPOINT_ID.match(value):
            raise ValueError(
                "endpoint id must be 1-32 lowercase letters, digits or '-', starting with a letter or digit"
            )
        if value in RESERVED_ENDPOINT_IDS:
            raise ValueError(f"endpoint id {value!r} is reserved")
        return value

    @field_validator("base_url")
    @classmethod
    def _valid_base_url(cls, value: str) -> str:
        # The key travels in a header, never in the URL; a URL with credentials, a query or a fragment is a typo
        # at best and would leak into traces and logs at worst.
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("base_url must be an http:// or https:// URL with a host")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("base_url must not contain credentials, a query or a fragment")
        return value.strip().rstrip("/")

    @property
    def identity(self) -> str:
        """Which server this is, without saying where: it changes with the URL (however it was edited), so runs on a
        moved endpoint never pool or resume with earlier ones. A plain hash would not do: an IP and port can be
        brute-forced from it in seconds, and setups travel in exported run bundles."""
        return hmac.new(self.salt.encode(), self.base_url.encode(), hashlib.sha256).hexdigest()[:12]
