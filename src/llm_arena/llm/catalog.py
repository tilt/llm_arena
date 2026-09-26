"""Model catalog: what is available on *this* machine and account, as ready-to-use ModelSpecs.

Pure part of discovery: the types plus builders that turn each provider's metadata JSON into
catalog entries (capabilities, tool mode, prices), keyed by the canonical reference
`provider:model`. Fetching that JSON is runtime-specific — `adapters.server.discovery` (httpx,
local servers included) or the browser engine (fetch, remote providers only).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from llm_arena.llm.pricing import known_price
from llm_arena.llm.spec import Capabilities, ModelSpec

Source = Literal["ollama", "lmstudio", "openai", "anthropic"]

# OpenAI lists every model the key may use, including audio, image and embedding models; the
# arena needs chat models only.
_OPENAI_CHAT_PREFIXES = ("gpt-5", "gpt-4.1", "gpt-4o", "o3", "o4")
_SNAPSHOT = re.compile(r"-\d{4}-\d{2}-\d{2}$")
_OPENAI_EXCLUDE = ("audio", "realtime", "transcribe", "tts", "search", "image", "embedding", "codex", "chat-latest")


@dataclass(frozen=True)
class CatalogEntry:
    spec: ModelSpec
    source: Source
    parameters: str | None = None  # e.g. "14.8B"
    quantization: str | None = None
    size_gb: float | None = None
    context_length: int | None = None
    loaded: bool | None = None
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    snapshot: bool = False  # dated OpenAI snapshot of a model family that is listed as well

    @property
    def ref(self) -> str:
        return self.spec.name

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["spec"] = self.spec.model_dump()
        data["ref"] = self.ref
        return data


@dataclass
class Catalog:
    entries: list[CatalogEntry] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # provider -> why it is unavailable

    def get(self, ref: str) -> CatalogEntry | None:
        return next((entry for entry in self.entries if entry.ref == ref), None)

    def specs(self) -> dict[str, ModelSpec]:
        return {entry.ref: entry.spec for entry in self.entries}

    def filter(
        self, *, needs: frozenset[str] = frozenset(), source: Source | None = None, snapshots: bool = False
    ) -> list[CatalogEntry]:
        """Entries offering every capability in `needs` — what a UI shows for a given role."""
        return [
            entry
            for entry in self.entries
            if (source is None or entry.source == source)
            and (snapshots or not entry.snapshot)
            and all(getattr(entry.spec.capabilities, need) for need in needs)
        ]


def ollama_entries(tags: list[dict[str, Any]], shows: list[dict[str, Any]], loaded: set[str]) -> list[CatalogEntry]:
    """From Ollama's /api/tags, the matching /api/show bodies, and the names in /api/ps."""
    entries = []
    for tag, info in zip(tags, shows, strict=True):
        capabilities = set(info.get("capabilities") or [])
        if capabilities and "completion" not in capabilities:
            continue  # embedding-only models
        context = next((v for k, v in (info.get("model_info") or {}).items() if k.endswith("context_length")), None)
        spec = ModelSpec(
            name=f"ollama:{tag['name']}",
            provider="ollama",
            model=tag["name"],
            # Without native tool support the JSON protocol still lets the model play the agentic scenarios.
            tool_mode="native" if "tools" in capabilities else "json",
            capabilities=Capabilities(
                tools="tools" in capabilities, vision="vision" in capabilities, reasoning="thinking" in capabilities
            ),
        )
        # MLX/safetensors models leave the tag details empty; /api/show still has them.
        details = {**(info.get("details") or {}), **{k: v for k, v in (tag.get("details") or {}).items() if v}}
        entries.append(
            CatalogEntry(
                spec=spec,
                source="ollama",
                parameters=details.get("parameter_size") or None,
                quantization=details.get("quantization_level") or None,
                size_gb=round(tag.get("size", 0) / 1e9, 1) or None,
                context_length=int(context) if context else None,
                loaded=tag["name"] in loaded,
                input_cost_per_mtok=0.0,
                output_cost_per_mtok=0.0,
            )
        )
    return entries


def lmstudio_entries(models: list[dict[str, Any]]) -> list[CatalogEntry]:
    """From LM Studio's /api/v0/models."""
    entries = []
    for model in models:
        if model.get("type") not in ("llm", "vlm"):
            continue
        tools = "tool_use" in (model.get("capabilities") or [])
        spec = ModelSpec(
            name=f"lmstudio:{model['id']}",
            provider="lmstudio",
            model=model["id"],
            tool_mode="native" if tools else "json",
            capabilities=Capabilities(tools=tools, vision=model.get("type") == "vlm"),
        )
        entries.append(
            CatalogEntry(
                spec=spec,
                source="lmstudio",
                quantization=model.get("quantization"),
                context_length=model.get("max_context_length"),
                loaded=model.get("state") == "loaded",
                input_cost_per_mtok=0.0,
                output_cost_per_mtok=0.0,
            )
        )
    return entries


def openai_entries(model_ids: list[str]) -> list[CatalogEntry]:
    """From OpenAI's /v1/models ids: chat models only, with list prices where known."""
    entries = []
    for model_id in sorted(model_ids):
        if not model_id.startswith(_OPENAI_CHAT_PREFIXES) or any(word in model_id for word in _OPENAI_EXCLUDE):
            continue
        spec = ModelSpec(
            name=f"openai:{model_id}",
            provider="openai",
            model=model_id,
            capabilities=Capabilities(vision=True, reasoning=model_id.startswith(("gpt-5", "o3", "o4"))),
        )
        entries.append(_priced(spec, "openai", snapshot=bool(_SNAPSHOT.search(model_id))))
    return entries


def anthropic_entries(models: list[dict[str, Any]]) -> list[CatalogEntry]:
    """From Anthropic's /v1/models. The arena does not send response_format to Claude (json_schema off)."""
    entries = []
    for model in models:
        model_id = model["id"]
        spec = ModelSpec(
            name=f"anthropic:{model_id}",
            provider="anthropic",
            model=model_id,
            capabilities=Capabilities(vision=True, reasoning=True, json_schema=False),
        )
        entry = _priced(spec, "anthropic")
        entries.append(replace(entry, context_length=model.get("max_input_tokens")))
    return entries


def _priced(spec: ModelSpec, source: Source, *, snapshot: bool = False) -> CatalogEntry:
    price = known_price(spec.model)
    return CatalogEntry(
        spec=spec,
        source=source,
        snapshot=snapshot,
        input_cost_per_mtok=price[0] if price else None,
        output_cost_per_mtok=price[1] if price else None,
    )
