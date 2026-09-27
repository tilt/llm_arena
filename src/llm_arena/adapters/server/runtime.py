"""Compose the server runtime: SDK clients, discovery, subprocess sandbox, live search, Hub datasets."""

from __future__ import annotations

import os

from llm_arena.adapters.server.clients import get_client
from llm_arena.adapters.server.discovery import discover
from llm_arena.adapters.server.hf_datasets import HubDatasetLoader
from llm_arena.adapters.server.httpx_transport import HttpxTransport
from llm_arena.adapters.server.live_search import live_search
from llm_arena.adapters.server.subprocess_sandbox import DockerSandbox, SubprocessSandbox
from llm_arena.benchmarks.hf import configure_loader
from llm_arena.core.errors import ConfigError
from llm_arena.decisions.jev import JevDecisionPolicy
from llm_arena.decisions.policy import DecisionPolicy
from llm_arena.runner.ports import Runtime


def jev_policy(model: str) -> DecisionPolicy:
    """Jev over httpx. The key is read per trial, so a key set in the app takes effect for the next run."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise ConfigError("Jev needs TYPESAFE_API_KEY (TypeSafe early access) in .env or on the Models page")
    return JevDecisionPolicy(HttpxTransport(), key, model=model)


def server_runtime(*, docker_sandbox: bool = False) -> Runtime:
    configure_loader(HubDatasetLoader())
    return Runtime(
        client_factory=get_client,
        discover=discover,
        sandbox=DockerSandbox() if docker_sandbox else SubprocessSandbox(),
        live_search=live_search,
        jev=jev_policy,
        name="server",
    )
