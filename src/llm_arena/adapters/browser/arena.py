"""The browser engine's entry point, called from the Pyodide web worker.

Wraps ArenaService with a browser Runtime: remote models only (OpenAI, Anthropic) with keys kept in
this worker's memory, fetch-based discovery using the shared catalog builders, a JS-bridged
sandbox, and benchmark files prefetched from the Hugging Face CDN. Methods take and return JSON
strings, which keeps the JS <-> Python bridge trivial and matches the local app's HTTP payloads.

All I/O is injected (transport, http_get, get_bytes, sandbox), so the server test suite exercises
this module with fakes.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from llm_arena.api import KeySource, RunListing, RuntimeResponse, StartRun
from llm_arena.benchmarks.base import Benchmark
from llm_arena.benchmarks.hf import HFSource, configure_loader, hub_url
from llm_arena.conformance import CASES, record
from llm_arena.core.errors import ConfigError
from llm_arena.llm.catalog import Catalog, anthropic_entries, openai_entries
from llm_arena.llm.client import LLMClient
from llm_arena.llm.http_client import ProtocolClient
from llm_arena.llm.protocols.anthropic_messages import API_VERSION
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.transport import ChatTransport, HttpResponse
from llm_arena.report.leaderboard import Leaderboard, build_leaderboards
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import RunEvent, RunFinished
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.runner.run import new_run_id
from llm_arena.sandbox.base import Sandbox
from llm_arena.scenarios.base import get_scenario, work_dir
from llm_arena.service import ArenaService

HttpGet = Callable[[str, dict[str, str]], Awaitable[HttpResponse]]
GetBytes = Callable[[str], Awaitable[bytes]]
Emit = Callable[[str], None]
PROVIDERS = ("openai", "anthropic")


class BrowserDatasetLoader:
    """Synchronous loader over files prefetched into the (in-memory) file system."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, source: HFSource) -> Path:
        return self.directory / source.repo.replace("/", "__") / source.revision / source.filename

    def load_rows(self, source: HFSource) -> list[dict[str, Any]]:
        path = self.path(source)
        if not path.exists():
            raise RuntimeError(f"dataset {source.repo} was not prefetched")
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        import duckdb  # Pyodide ships DuckDB; loaded only when a parquet benchmark is used

        with duckdb.connect() as db:
            cursor = db.execute("SELECT * FROM read_parquet(?)", [str(path)])
            columns = [column[0] for column in cursor.description or []]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


class BrowserArena:
    def __init__(
        self,
        *,
        transport: ChatTransport,
        http_get: HttpGet,
        get_bytes: GetBytes,
        emit: Emit,
        sandbox: Sandbox | None = None,
        load_package: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._transport = transport
        self._http_get = http_get
        self._get_bytes = get_bytes
        self._emit = emit
        self._load_package = load_package
        self._keys: dict[str, str] = {}
        self._stores: dict[str, MemoryStore] = {}
        self._finished: set[str] = set()
        self.datasets = BrowserDatasetLoader(work_dir() / "hf")
        configure_loader(self.datasets)
        runtime = Runtime(client_factory=self._client, discover=self._discover, sandbox=sandbox, name="browser")
        self.service = ArenaService(
            runtime, store_factory=lambda run_id: self._stores.setdefault(run_id, MemoryStore())
        )

    # ---- keys -----------------------------------------------------------------------------
    def set_key(self, provider: str, key: str) -> None:
        if provider not in PROVIDERS:
            raise ConfigError(f"browser mode supports {', '.join(PROVIDERS)} keys")
        self._keys[provider] = key.strip()

    def clear_key(self, provider: str) -> None:
        self._keys.pop(provider, None)

    def key_status(self) -> dict[str, KeySource]:
        return {provider: "session" if provider in self._keys else "missing" for provider in PROVIDERS}

    # ---- API (JSON in / JSON out) ---------------------------------------------------------
    async def runtime(self) -> str:
        info = await self.service.runtime_info()
        return RuntimeResponse(**info.model_dump(), keys=self.key_status()).model_dump_json()

    def scenarios(self) -> str:
        return json.dumps([manifest.model_dump() for manifest in self.service.list_scenarios()])

    async def models(self, refresh: bool = False) -> str:
        catalog = await self.service.catalog(refresh=refresh)
        return json.dumps(
            {"models": [entry.as_dict() for entry in catalog.filter()], "aliases": {}, "unavailable": catalog.errors},
            default=str,
        )

    async def estimate(self, experiment_json: str) -> str:
        experiment = ExperimentConfig.model_validate_json(experiment_json)
        await self._prefetch(experiment.scenarios)
        return (await self.service.estimate(experiment)).model_dump_json()

    async def start_run(self, request_json: str) -> str:
        request = StartRun.model_validate_json(request_json)
        await self._prefetch(request.experiment.scenarios)
        run_id = request.run_id or new_run_id(request.experiment.name)
        return await self.service.start_run(
            request.experiment, sink=lambda event: self._sink(run_id, event), run_id=run_id, live=False
        )

    def cancel(self, run_id: str) -> None:
        self.service.cancel(run_id)

    def runs(self) -> str:
        listings = []
        for run_id, store in reversed(list(self._stores.items())):
            data = store.load_run()
            listings.append(
                RunListing(
                    run_id=run_id,
                    name=str(data.run.get("name", "")),
                    created_at=str(data.run.get("created_at", "")),
                    trials=len(data.trials),
                    passed=sum(bool(t["passed"]) for t in data.trials),
                    errors=sum(t["status"] != "ok" for t in data.trials),
                    active=run_id not in self._finished,
                )
            )
        return TypeAdapter(list[RunListing]).dump_json(listings).decode()

    def leaderboard(self, trials_json: str) -> str:
        """Leaderboards over trial rows the UI collected from this tab's runs and saved bundles."""
        boards = build_leaderboards(json.loads(trials_json))
        return TypeAdapter(list[Leaderboard]).dump_json(boards).decode()

    def bundle(self, run_id: str) -> str:
        # Browser runs live only in this tab: the bundle carries traces and files into IndexedDB / exports.
        return self.service.run_bundle(run_id, artifacts=True).model_dump_json()

    async def selftest(self, vectors_json: str) -> str:
        """Replay the conformance cases in this runtime and compare with the Python engine's vectors."""
        expected = json.loads(vectors_json)
        sandbox = self.service.runtime.sandbox
        results: list[dict[str, Any]] = []
        for case in CASES:
            vector = expected.get(case.id)
            if vector is None:
                continue
            if "sandbox" in get_scenario(case.scenario).requires and sandbox is None:
                results.append({"case": case.id, "status": "skipped", "reason": "no sandbox"})
                continue
            actual = await record(case, sandbox)
            mismatches = [key for key in ("requests", "final", "scores") if actual[key] != vector[key]]
            results.append({"case": case.id, "status": "fail" if mismatches else "pass", "mismatches": mismatches})
        return json.dumps(results)

    # ---- runtime plumbing -----------------------------------------------------------------
    def _sink(self, run_id: str, event: RunEvent) -> None:
        if isinstance(event, RunFinished):
            self._finished.add(run_id)
        self._emit(json.dumps({"run_id": run_id, "event": event.model_dump()}))

    def _client(self, spec: ModelSpec) -> LLMClient:
        if spec.provider not in PROVIDERS:
            raise ConfigError(f"{spec.name}: browser mode runs remote models only (install the app for local models)")
        key = self._keys.get(spec.provider)
        if not key:
            raise ConfigError(f"{spec.name}: set your {spec.provider} API key first")
        return ProtocolClient(spec, self._transport, api_key=key, browser=True)

    async def _discover(self) -> Catalog:
        catalog = Catalog()
        for provider in PROVIDERS:
            key = self._keys.get(provider)
            if not key:
                catalog.errors[provider] = "no API key set"
                continue
            try:
                catalog.entries.extend(await self._list_models(provider, key))
            except Exception as exc:  # reported per provider, like server discovery
                catalog.errors[provider] = f"{type(exc).__name__}: {exc}"[:200]
        return catalog

    async def _list_models(self, provider: str, key: str) -> list[Any]:
        if provider == "openai":
            response = await self._http_get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
            _raise_for_status(response)
            return openai_entries([m["id"] for m in response.data.get("data", [])])
        response = await self._http_get(
            "https://api.anthropic.com/v1/models?limit=100",
            {"x-api-key": key, "anthropic-version": API_VERSION, "anthropic-dangerous-direct-browser-access": "true"},
        )
        _raise_for_status(response)
        return anthropic_entries(response.data.get("data", []))

    async def _prefetch(self, scenario_names: list[str]) -> None:
        for name in scenario_names:
            scenario = get_scenario(name)
            for source in scenario.sources if isinstance(scenario, Benchmark) else ():
                path = self.datasets.path(source)
                if source.filename.endswith(".parquet") and self._load_package is not None:
                    await self._load_package("duckdb")  # Pyodide loads it on demand, once
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(await self._get_bytes(hub_url(source)))


def _raise_for_status(response: HttpResponse) -> None:
    if response.status >= 400:
        detail = response.data.get("error", response.data) if isinstance(response.data, dict) else response.data
        raise RuntimeError(f"HTTP {response.status}: {detail}")
