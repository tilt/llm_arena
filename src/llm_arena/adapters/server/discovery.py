"""Server-side discovery: query Ollama, LM Studio, OpenAI and Anthropic, build the catalog.

Unreachable providers are reported, not raised: a machine without LM Studio still gets a catalog.
"""

from __future__ import annotations

import asyncio

import httpx

from llm_arena.llm.catalog import (
    Catalog,
    CatalogEntry,
    Source,
    anthropic_entries,
    lmstudio_entries,
    ollama_entries,
    openai_entries,
)
from llm_arena.llm.protocols.anthropic_messages import API_VERSION
from llm_arena.llm.registry import resolve_api_key, resolve_base_url
from llm_arena.llm.spec import ModelSpec, Provider

ALL_SOURCES: tuple[Source, ...] = ("ollama", "lmstudio", "openai", "anthropic")


async def discover(
    timeout_s: float = 3.0,
    sources: tuple[Source, ...] = ALL_SOURCES,
    transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
) -> Catalog:
    catalog = Catalog()
    probes = {"ollama": _ollama, "lmstudio": _lmstudio, "openai": _openai, "anthropic": _anthropic}
    async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as http:
        results = await asyncio.gather(*(probes[source](http) for source in sources), return_exceptions=True)
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            catalog.errors[source] = f"{type(result).__name__}: {result}"[:200]
        else:
            catalog.entries.extend(result)
    return catalog


def _root(provider: Provider) -> str:
    base = resolve_base_url(ModelSpec(name="probe", provider=provider, model="-")) or ""
    return base.removesuffix("/").removesuffix("/v1")


def _key(provider: Provider, env_name: str) -> str:
    key = resolve_api_key(ModelSpec(name="probe", provider=provider, model="-"))
    if key in ("", "missing-key"):
        raise RuntimeError(f"{env_name} is not set")
    return key


async def _ollama(http: httpx.AsyncClient) -> list[CatalogEntry]:
    root = _root("ollama")
    tags = (await http.get(f"{root}/api/tags")).raise_for_status().json().get("models", [])
    responses = await asyncio.gather(*(http.post(f"{root}/api/show", json={"model": tag["name"]}) for tag in tags))
    shows = [response.json() if response.status_code == 200 else {} for response in responses]
    loaded = {m["name"] for m in (await http.get(f"{root}/api/ps")).json().get("models", [])}
    return ollama_entries(tags, shows, loaded)


async def _lmstudio(http: httpx.AsyncClient) -> list[CatalogEntry]:
    models = (await http.get(f"{_root('lmstudio')}/api/v0/models")).raise_for_status().json().get("data", [])
    return lmstudio_entries(models)


async def _openai(http: httpx.AsyncClient) -> list[CatalogEntry]:
    key = _key("openai", "OPENAI_API_KEY")
    response = await http.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"})
    return openai_entries([m["id"] for m in response.raise_for_status().json().get("data", [])])


async def _anthropic(http: httpx.AsyncClient) -> list[CatalogEntry]:
    key = _key("anthropic", "ANTHROPIC_API_KEY")
    response = await http.get(
        "https://api.anthropic.com/v1/models?limit=100", headers={"x-api-key": key, "anthropic-version": API_VERSION}
    )
    return anthropic_entries(response.raise_for_status().json().get("data", []))
