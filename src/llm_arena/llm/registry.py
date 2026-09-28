"""Provider defaults and loading of model specs from YAML or ad-hoc references."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from llm_arena.llm.spec import ModelSpec, Provider


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
    defaults = PROVIDERS[spec.provider]
    env_name = spec.api_key_env or defaults.api_key_env
    key = os.getenv(env_name) if env_name else None
    return key or defaults.placeholder_key or "missing-key"


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


# Call settings a reference may carry after '#', e.g. "ollama:qwen3:4b#reasoning=none" (thinking off) or
# "openai:gpt-5-mini#reasoning=low,temperature=0": portable across runtimes, no alias file needed.
_SETTINGS = {"reasoning": "reasoning_effort", "tools": "tool_mode", "temperature": "temperature"}


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
            update[_SETTINGS[key]] = float(value) if key == "temperature" else value
        return ModelSpec.model_validate({**spec.model_dump(), **update})
    if ref in specs:
        return specs[ref]
    if discovered and ref in discovered:
        return discovered[ref]
    try:
        return parse_model_ref(ref)
    except ValueError as exc:
        raise KeyError(f"Unknown model {ref!r}; known aliases: {sorted(specs)}") from exc
