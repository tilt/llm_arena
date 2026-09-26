from __future__ import annotations

import pytest

from llm_arena.llm.catalog import Catalog, CatalogEntry
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import RunEvent, RunFinished
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.service import ArenaService

GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
NANO = ModelSpec(name="openai:gpt-4.1-nano", provider="openai", model="gpt-4.1-nano")
MYSTERY = ModelSpec(name="openai:gpt-9", provider="openai", model="gpt-9")


def _reply(messages: list[dict[str, object]]) -> str:
    return '{"verdict": "accept", "issues": []}' if "verdict" in str(messages) else GOOD_SQL


def _service() -> tuple[ArenaService, dict[str, MemoryStore]]:
    stores: dict[str, MemoryStore] = {}

    async def discover() -> Catalog:
        return Catalog(entries=[CatalogEntry(spec=NANO, source="openai")], errors={"ollama": "ConnectError: refused"})

    def client_factory(spec: ModelSpec) -> LLMClient:
        return ScriptedLLM([_reply])

    runtime = Runtime(client_factory=client_factory, discover=discover, name="test")
    return ArenaService(runtime, store_factory=lambda run_id: stores.setdefault(run_id, MemoryStore())), stores


def _experiment(model: str) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "name": "svc",
            "scenarios": ["reflection_sql"],
            "task_ids": ["harborview_march_rentals"],
            "configs": [{"name": "c", "roles": {"*": model}}],
        }  # fmt: skip
    )


def test_manifests_cover_every_scenario_with_wiki_links() -> None:
    service, _ = _service()
    manifests = {m.id: m for m in service.list_scenarios()}
    assert len(manifests) == 15
    assert manifests["chart_codegen"].requires == ["sandbox"]
    assert next(r for r in manifests["chart_codegen"].roles if r.name == "critic").needs == ["vision"]
    assert manifests["react_multihop"].params[0].choices == ["react", "act", "cot"]
    assert manifests["gsm8k"].kind == "benchmark" and manifests["gsm8k"].tasks == 100  # counted without downloading
    for manifest in manifests.values():
        assert manifest.wiki and all(
            link.url.startswith("https://tilt.github.io/data-science-wiki/") for link in manifest.wiki
        )
    assert any("agent-loops#code-as-an-action" in link.url for link in manifests["shop_codeact"].wiki)


async def test_runtime_info_reports_providers_without_keys() -> None:
    service, _ = _service()
    info = await service.runtime_info()
    assert info.providers == {"openai": "available", "ollama": "ConnectError: refused"}
    assert info.runtime == "test" and not info.sandbox


async def test_estimate_prices_known_models_and_flags_unknown_ones() -> None:
    service, _ = _service()
    estimate = await service.estimate(_experiment("openai:gpt-4.1-nano"))
    assert estimate.trials == 1 and estimate.tokens == 2500
    assert estimate.cost_usd == pytest.approx((2500 * 0.8 * 0.10 + 2500 * 0.2 * 0.40) / 1e6)
    service.model_specs["openai:gpt-9"] = MYSTERY
    assert (await service.estimate(_experiment("openai:gpt-9"))).unknown_prices == ["openai:gpt-9"]


async def test_start_run_streams_events_and_returns_a_bundle() -> None:
    service, stores = _service()
    events: list[RunEvent] = []
    run_id = await service.start_run(_experiment("openai:gpt-4.1-nano"), sink=events.append, run_id="r1")
    assert await service.wait(run_id) == "r1"
    assert isinstance(events[-1], RunFinished)
    bundle = service.run_bundle("r1")
    assert bundle.trials[0]["passed"] and bundle.summary["configs"][0]["pass_rate"] == 1.0
    assert bundle.traces[bundle.trials[0]["trial_id"]]["spans"]
    bundle.model_dump_json()  # the bundle is a JSON contract
