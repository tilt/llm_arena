"""Compose the server runtime: SDK clients, discovery, subprocess sandbox, live search, Hub datasets."""

from __future__ import annotations

import os

import httpx

from llm_arena.adapters.server.clients import get_client
from llm_arena.adapters.server.discovery import discover
from llm_arena.adapters.server.hf_datasets import HubDatasetLoader
from llm_arena.adapters.server.httpx_transport import HttpxTransport
from llm_arena.adapters.server.live_search import live_search
from llm_arena.adapters.server.subprocess_sandbox import DockerSandbox, SubprocessSandbox
from llm_arena.benchmarks.hf import configure_loader
from llm_arena.core.errors import ConfigError
from llm_arena.decisions.config import Service
from llm_arena.decisions.jev import OLLAYA_BASE_URL, JevDecisionPolicy
from llm_arena.decisions.policy import DecisionPolicy
from llm_arena.runner.ports import Runtime


def decision_service(service: Service, model: str) -> DecisionPolicy:
    """Jev (TypeSafe, needs TYPESAFE_API_KEY, read per trial so a key set in the app applies to the next run) or
    a local Ollaya server (no key, free; the first call loads the model, hence the longer timeout)."""
    if service == "ollaya":
        return JevDecisionPolicy(HttpxTransport(), None, model=model, base_url=OLLAYA_BASE_URL, service="ollaya",
                                 usd_per_mtok=0.0, timeout_s=180.0)  # fmt: skip
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise ConfigError("Jev needs TYPESAFE_API_KEY (TypeSafe early access) in .env or on the Models page")
    return JevDecisionPolicy(HttpxTransport(), key, model=model)


async def decision_status() -> dict[str, tuple[str, list[str]]]:
    jev = (
        ("available", ["jev-latest"]) if os.environ.get("TYPESAFE_API_KEY", "").strip() else ("no TYPESAFE_API_KEY", [])
    )
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{OLLAYA_BASE_URL}/v1/models")
            models = [m["name"] for m in response.json().get("models", [])]
        ollaya = (
            ("available", models) if models else ("Ollaya is running but has no models (ollaya pull winnow:e4b)", [])
        )
    except (httpx.HTTPError, ValueError):
        ollaya = (f"Ollaya not reachable at {OLLAYA_BASE_URL} (start it with: ollaya serve)", [])
    return {"jev": jev, "ollaya": ollaya}


def server_runtime(*, docker_sandbox: bool = False) -> Runtime:
    configure_loader(HubDatasetLoader())
    return Runtime(
        client_factory=get_client,
        discover=discover,
        sandbox=DockerSandbox() if docker_sandbox else SubprocessSandbox(),
        live_search=live_search,
        decision_services=decision_service,
        decision_status=decision_status,
        name="server",
    )
