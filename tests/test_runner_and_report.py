from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.adapters.server.report_html import build_report
from llm_arena.core.errors import CapabilityError, ConfigError
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.llm.types import LLMResponse, Usage
from llm_arena.report.aggregate import summarize
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import BudgetExceeded, RunEvent, RunFinished, TrialFinished
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import RunStore, Runtime
from llm_arena.runner.run import ExperimentRunner

GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)

SPECS = {
    "good": ModelSpec(name="good", provider="openai_compatible", model="good"),
    "bad": ModelSpec(name="bad", provider="openai_compatible", model="bad"),
    "blind": ModelSpec(
        name="blind", provider="openai_compatible", model="blind", capabilities=Capabilities(vision=False)
    ),
}


def factory(spec: ModelSpec) -> LLMClient:
    if spec.name == "good":
        return ScriptedLLM([_good_reply])
    return ScriptedLLM(["```sql\nSELECT 1\n```"], name=spec.name)


def _good_reply(messages: list[dict[str, object]]) -> str:
    text = str(messages)
    if "verdict" in text:  # critic prompt asks for the Critique schema
        return '{"verdict": "accept", "issues": []}'
    if "RESPONSE A" in text:
        return '{"rationale": "A is better", "winner": "A"}'
    return GOOD_SQL


def _experiment(**overrides: object) -> ExperimentConfig:
    data = {
        "name": "t",
        "scenarios": ["reflection_sql"],
        "task_ids": ["harborview_march_rentals", "total_refunds"],
        "repeats": 2,
        "configs": [{"name": "good-cfg", "roles": {"*": "good"}}, {"name": "bad-cfg", "roles": {"*": "bad"}}],
    }
    return ExperimentConfig.model_validate({**data, **overrides})


def _runner(
    experiment: ExperimentConfig,
    store: RunStore | None = None,
    *,
    client_factory: Callable[[ModelSpec], LLMClient] = factory,
    specs: dict[str, ModelSpec] = SPECS,
    run_id: str | None = None,
    events: list[RunEvent] | None = None,
) -> ExperimentRunner:
    sink = events.append if events is not None else (lambda event: None)
    return ExperimentRunner(
        experiment, Runtime(client_factory=client_factory), store=store, run_id=run_id, model_specs=specs, sink=sink
    )


async def test_run_persists_trials_emits_events_and_builds_report(tmp_path: Path) -> None:
    events: list[RunEvent] = []
    store = DuckDBStore(tmp_path / "run")
    await _runner(_experiment(), store, events=events).run()
    rows = store.load_run().trials
    assert len(rows) == 8
    assert {(r["config"], r["task_id"]) for r in rows if r["passed"]} == {("good-cfg", "harborview_march_rentals")}
    finished = [e for e in events if isinstance(e, TrialFinished)]
    assert len(finished) == 8 and finished[-1].done == 8 and isinstance(events[-1], RunFinished)
    report = build_report(tmp_path / "run", inline_plotly=False).read_text(encoding="utf-8")
    assert "LLM Arena Report" in report and "good-cfg" in report and "harborview_march_rentals" in report


async def test_memory_and_duckdb_stores_give_the_same_summary(tmp_path: Path) -> None:
    memory, duck = MemoryStore(), DuckDBStore(tmp_path / "run")
    await _runner(_experiment(), memory, run_id="same").run()
    await _runner(_experiment(), duck, run_id="same").run()
    from_memory, from_duck = summarize(memory.load_run()), summarize(duck.load_run())
    assert [(c.scenario, c.config, c.pass_rate) for c in from_memory.configs] == [
        (c.scenario, c.config, c.pass_rate) for c in from_duck.configs
    ]
    trial_id = next(iter(memory.trials))

    def shape(trace: dict[str, object] | None) -> list[tuple[object, ...]]:
        assert trace is not None
        return [(span["kind"], span["name"], span["output"]) for span in trace["spans"]]  # type: ignore[attr-defined,index]

    assert shape(memory.load_trace(trial_id)) == shape(duck.load_trace(trial_id))


async def test_resume_skips_finished_trials_and_retries_errors(tmp_path: Path) -> None:
    await _runner(_experiment(), DuckDBStore(tmp_path / "r1"), run_id="r1").run()
    calls: list[str] = []

    def counting_factory(spec: ModelSpec) -> LLMClient:
        calls.append(spec.name)
        return factory(spec)

    await _runner(_experiment(), DuckDBStore(tmp_path / "r1"), run_id="r1", client_factory=counting_factory).run()
    # The "bad" model cannot produce a valid critique, so its trials errored and are retried; "good" ones are skipped.
    assert calls == ["bad"]


async def test_budget_limit_stops_the_run() -> None:
    class Pricey(ScriptedLLM):
        async def complete(self, messages, **kwargs):  # type: ignore[no-untyped-def]
            reply = await super().complete(messages, **kwargs)
            return LLMResponse(content=reply.content, raw_message=reply.raw_message, usage=Usage(10, 10, 0.1, 0.30))

    events: list[RunEvent] = []
    store = MemoryStore()
    experiment = _experiment(configs=[{"name": "c", "roles": {"*": "good"}}], repeats=5, max_cost_usd=1.0)
    await _runner(experiment, store, client_factory=lambda spec: Pricey([_good_reply]), events=events).run()
    finished = events[-1]
    assert isinstance(finished, RunFinished) and finished.stopped_early
    assert any(isinstance(e, BudgetExceeded) for e in events)
    assert len(store.trials) < 10  # 2 tasks x 5 repeats would be 10 trials without the limit
    assert 1.0 <= finished.spent_usd < 1.0 + 0.30 * 2  # at most the calls already in flight overshoot


def test_capability_check_fails_fast() -> None:
    experiment = _experiment(
        scenarios=["chart_codegen"], task_ids=None, configs=[{"name": "c", "roles": {"*": "blind"}}]
    )
    with pytest.raises(CapabilityError):
        _runner(experiment).plan()


def test_unknown_param_and_model_are_config_errors() -> None:
    bad_param = _experiment(
        configs=[{"name": "c", "roles": {"*": "good"}, "scenario_params": {"reflection_sql": {"x": 1}}}]
    )
    with pytest.raises(ConfigError):
        _runner(bad_param).plan()
    with pytest.raises(ConfigError):
        _runner(_experiment(configs=[{"name": "c", "roles": {"*": "ghost"}}])).plan()


async def test_arena_battles_and_ratings(tmp_path: Path) -> None:
    experiment = ExperimentConfig.model_validate(
        {
            "name": "arena",
            "scenarios": ["reflection_writing"],
            "task_ids": ["release_notes"],
            "judge": "good",
            "arena": {"enabled": True},
            "configs": [{"name": "a", "roles": {"*": "good"}}, {"name": "b", "roles": {"*": "bad"}}],
        }
    )

    def writing_factory(spec: ModelSpec) -> LLMClient:
        def reply(messages: list[dict[str, object]]) -> str:
            text = str(messages)
            if "RESPONSE A" in text:
                return '{"rationale": "first", "winner": "A"}'
            if "verdicts" in text:
                return '{"verdicts": [{"criterion": "accuracy", "rationale": "ok", "score": 4}]}'
            if "verdict" in text:
                return '{"verdict": "accept"}'
            return "- Offline mode\n- Dusk theme\n- Search 3x faster\n- Sync fix"

        return ScriptedLLM([reply], name=spec.name)

    store = DuckDBStore(tmp_path / "arena")
    await _runner(experiment, store, client_factory=writing_factory).run()
    battles = [(b["config_a"], b["config_b"], b["winner"]) for b in store.load_run().battles]
    # The judge always prefers position A, so the swapped comparison disagrees: position bias becomes a tie.
    assert battles == [("a", "b", "tie")]
    assert "Arena ratings" in build_report(tmp_path / "arena", inline_plotly=False).read_text(encoding="utf-8")


async def test_trials_on_a_local_endpoint_run_one_at_a_time() -> None:
    active = 0
    peak = 0

    class SlowLLM(ScriptedLLM):
        async def complete(self, messages, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return await super().complete(messages, **kwargs)

    local = ModelSpec(name="local", provider="ollama", model="m")
    experiment = _experiment(configs=[{"name": "c", "roles": {"*": "local"}}], repeats=3)
    runner = _runner(
        experiment, MemoryStore(), client_factory=lambda spec: SlowLLM([_good_reply]), specs={"local": local}
    )
    await runner.run()
    assert peak == 1
