"""Provider defaults and loading of model specs from YAML or ad-hoc references."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from llm_arena.llm.errors import LLMError
from llm_arena.llm.spec import Endpoint, ModelSpec, Provider, key_transport_ok


@dataclass(frozen=True)
class ProviderDefaults:
    base_url_env: str | None
    base_url: str | None
    api_key_env: str | None
    placeholder_key: str  # local servers ignore the key, but the OpenAI SDK insists on one
    concurrency: int


PROVIDERS: dict[str, ProviderDefaults] = {
    "openai": ProviderDefaults(None, None, "OPENAI_API_KEY", "", 8),
    "anthropic": ProviderDefaults(
        "ARENA_ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "", 4
    ),
    # Local servers get concurrency 1: parallel requests on one GPU mostly add queueing
    # latency and distort the per-call latency we report.
    "ollama": ProviderDefaults("ARENA_OLLAMA_BASE_URL", "http://localhost:11434/v1", None, "ollama", 1),
    "lmstudio": ProviderDefaults("ARENA_LMSTUDIO_BASE_URL", "http://localhost:1234/v1", None, "lm-studio", 1),
    "openai_compatible": ProviderDefaults(
        "ARENA_OPENAI_COMPATIBLE_BASE_URL", None, "ARENA_OPENAI_COMPATIBLE_KEY", "none", 4
    ),
}


def resolve_base_url(spec: ModelSpec) -> str | None:
    if spec.base_url:
        return spec.base_url
    defaults = PROVIDERS[spec.provider]
    if defaults.base_url_env and os.getenv(defaults.base_url_env):
        return os.environ[defaults.base_url_env]
    return defaults.base_url


def resolve_api_key(spec: ModelSpec) -> str:
    if spec.endpoint:
        # A named endpoint's key comes only from the env var its YAML names (or, in the app, from the session, which
        # the client factory passes in): never from a provider-wide variable that may belong to another host.
        key = os.getenv(spec.api_key_env) if spec.api_key_env else None
        return key or "none"
    defaults = PROVIDERS[spec.provider]
    env_name = spec.api_key_env or defaults.api_key_env
    key = os.getenv(env_name) if env_name else None
    return key or defaults.placeholder_key or "missing-key"


def check_key_transport(spec: ModelSpec, key: str | None = None) -> None:
    """Refuse to send a named endpoint's key in cleartext over the internet (http:// to a public host)."""
    if spec.provider != "openai_compatible":
        return
    key = resolve_api_key(spec) if key is None else key
    base_url = resolve_base_url(spec)
    if key not in ("", "none", "missing-key") and base_url and not key_transport_ok(base_url):
        raise LLMError(
            f"{spec.name}: its endpoint has a key but no https URL; use https:// so the key is not sent in cleartext"
        )


def bound_session_key(
    spec: ModelSpec, endpoints: Mapping[str, Endpoint], session: Callable[[str], str | None]
) -> str | None:
    """The session key for a named endpoint's model, only while the endpoint still has the URL the spec was resolved
    for: a key entered after a move belongs to the new URL, never to a spec that still points at the old one."""
    endpoint = endpoints.get(spec.endpoint) if spec.endpoint else None
    return session(endpoint.id) if endpoint and endpoint.base_url == spec.base_url else None


def resolve_concurrency(spec: ModelSpec) -> int:
    return spec.concurrency or PROVIDERS[spec.provider].concurrency


def parse_model_ref(ref: str) -> ModelSpec:
    """Build a spec from 'provider:model' (e.g. 'lmstudio:qwen/qwen3-14b', 'openai:gpt-4.1-mini').

    Convenient on the command line; YAML specs are preferred for anything with capabilities.
    """
    provider, sep, model = ref.partition(":")
    if not sep or provider not in PROVIDERS:
        raise ValueError(
            f"Model reference {ref!r} must look like '<provider>:<model>' with provider in {list(PROVIDERS)}"
        )
    return ModelSpec(name=ref, provider=cast(Provider, provider), model=model)


def load_model_specs(path: str | Path) -> dict[str, ModelSpec]:
    """Load `models:` from YAML. Entries may set `defaults:` shared by every model."""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    shared = raw.get("defaults", {})
    specs: dict[str, ModelSpec] = {}
    for name, entry in (raw.get("models") or {}).items():
        spec = ModelSpec.model_validate({**shared, **entry, "name": name})
        specs[name] = spec
    return specs


def load_endpoints(path: str | Path) -> dict[str, Endpoint]:
    """Load `endpoints: {id: {base_url, ...}}` from YAML; a missing file means no endpoints."""
    path = Path(path)
    if not path.exists():
        return {}
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        endpoint_id: Endpoint.model_validate({**(entry or {}), "id": endpoint_id})
        for endpoint_id, entry in (raw.get("endpoints") or {}).items()
    }


def save_endpoint(path: str | Path, endpoint_id: str, endpoint: Endpoint | None) -> None:
    """Write (or with None remove) one endpoint in a local file. Keys are never written, only their env var."""
    path = Path(path)
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    endpoints = dict(raw.get("endpoints") or {})
    if endpoint is None:
        endpoints.pop(endpoint_id, None)
    else:
        endpoints[endpoint_id] = endpoint.model_dump(mode="json", exclude={"id"}, exclude_none=True)
    path.write_text(yaml.safe_dump({"endpoints": endpoints}, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _unsalted(path: Path) -> bool:
    if not path.exists():
        return False
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return any("salt" not in (entry or {}) for entry in (raw.get("endpoints") or {}).values())


class EndpointStore:
    """The named endpoints of one process: loaded from YAML, edited by the local app, saved back when it has a
    file. Keys are not part of it: an env key is named by `api_key_env`, a session key stays in memory.

    Each endpoint carries a random salt for its identity; one written by hand without it gets one on first load,
    saved back so the identity stays stable across processes."""

    def __init__(self, path: str | Path | None = None, endpoints: Mapping[str, Endpoint] | None = None) -> None:
        self.path = Path(path) if path else None
        self._endpoints = dict(endpoints if endpoints is not None else load_endpoints(self.path) if self.path else {})
        if self.path and endpoints is None and _unsalted(self.path):
            for endpoint in self._endpoints.values():
                save_endpoint(self.path, endpoint.id, endpoint)

    def all(self) -> dict[str, Endpoint]:
        return dict(self._endpoints)

    def get(self, endpoint_id: str) -> Endpoint | None:
        return self._endpoints.get(endpoint_id)

    def put(self, endpoint: Endpoint) -> Endpoint | None:
        """Add or replace; returns the previous definition."""
        previous = self._endpoints.get(endpoint.id)
        self._endpoints[endpoint.id] = endpoint
        if self.path:
            save_endpoint(self.path, endpoint.id, endpoint)
        return previous

    def remove(self, endpoint_id: str) -> Endpoint | None:
        previous = self._endpoints.pop(endpoint_id, None)
        if previous and self.path:
            save_endpoint(self.path, endpoint_id, None)
        return previous


# Call settings a reference may carry after '#', e.g. "ollama:qwen3:4b#reasoning=none" (thinking off) or
# "openai:gpt-5-mini#reasoning=low,temperature=0,max_tokens=4096": portable across runtimes, no alias file needed.
# `temperature=none` sends no temperature (models that reject one); max_tokens makes a strict budget possible.
_SETTINGS = {
    "reasoning": "reasoning_effort",
    "tools": "tool_mode",
    "temperature": "temperature",
    "max_tokens": "max_tokens",
}


def _setting_value(key: str, value: str) -> object:
    if key == "temperature":
        return None if value == "none" else float(value)
    if key == "max_tokens":
        tokens = int(value)
        if tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        return tokens
    return value


def resolve_model(ref: str, specs: dict[str, ModelSpec], discovered: dict[str, ModelSpec] | None = None) -> ModelSpec:
    """Resolve a model reference: curated YAML alias → discovered model → ad-hoc 'provider:model'.

    Discovered specs carry real capabilities (tools, vision, thinking) from the server; an ad-hoc
    reference only gets defaults, so discovery should run before planning when possible. Settings after
    '#' apply on top of whatever the base reference resolves to.
    """
    base, _, settings = ref.partition("#")
    if settings:
        spec = resolve_model(base, specs, discovered)
        update: dict[str, object] = {"name": ref}
        for item in filter(None, settings.split(",")):
            key, _, value = item.partition("=")
            if key not in _SETTINGS or not value:
                raise KeyError(f"{ref!r}: unknown setting {key!r}; use {', '.join(_SETTINGS)} (e.g. #reasoning=none)")
            try:
                update[_SETTINGS[key]] = _setting_value(key, value)
            except ValueError as exc:
                raise KeyError(f"{ref!r}: invalid {key} {value!r}: {exc}") from exc
        return ModelSpec.model_validate({**spec.model_dump(), **update})
    if ref in specs:
        return specs[ref]
    if discovered and ref in discovered:
        return discovered[ref]
    try:
        return parse_model_ref(ref)
    except ValueError as exc:
        raise KeyError(f"Unknown model {ref!r}; known aliases: {sorted(specs)}") from exc
