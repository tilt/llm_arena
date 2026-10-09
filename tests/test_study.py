"""Replacement studies: a baseline plus one swapped step per configuration, reported against the baseline. Any
configuration can name its baseline (compare_to); a study sets it on its swaps."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.report.aggregate import summarize
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.runner.presets import ModelPreset
from llm_arena.runner.rename import RenameRun, rename_data
from llm_arena.runner.run import ExperimentRunner
from llm_arena.runner.study import StudyConfig, expand, short
from llm_arena.scenarios.base import get_scenario

WEAK = ModelPreset(label="Weak", models={"text": "weak", "code": "weak", "agent": "weak", "decision": "weak"})
GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
SPECS = {name: ModelSpec(name=name, provider="openai_compatible", model=name) for name in ("weak", "strong")}


def test_expansion_names_roles_and_skips_what_the_baseline_already_uses() -> None:
    scenarios = [get_scenario("reflection_sql"), get_scenario("reflection_writing"), get_scenario("support_desk")]
    study = StudyConfig(baseline="weak", candidates=["strong", "weak", "ollaya:winnow:e4b"])
    configs = expand(study, scenarios, WEAK)
    names = [c["name"] for c in configs]
    assert names[0] == "baseline"
    # critic exists in both reflection scenarios: one config swaps it in both; "weak" is the baseline itself.
    critic = next(c for c in configs if c["name"] == "critic→strong")
    assert critic["scenario_roles"] == {
        "reflection_sql": {"critic": "strong"},
        "reflection_writing": {"critic": "strong"},
    }
    assert critic["compare_to"] == "baseline"
    assert not any(n.endswith("→weak") for n in names)
    assert "decider→strong" not in names  # decision roles only when asked for
    service = next(c for c in configs if c["name"] == "decisions→winnow:e4b")
    assert service["scenarios"] == ["support_desk"] and service["decisions"]["policy"] == "ollaya"
    assert short("ollama:qwen3:4b#reasoning=none") == "qwen3:4b (no thinking)"


def factory(spec: ModelSpec) -> LLMClient:
    if spec.name == "strong":  # a critic that catches the wrong query; the generator then fixes it
        return ScriptedLLM(['{"verdict": "revise", "issues": ["filter by city"]}'], name="strong")

    def weak(messages: list[dict[str, object]]) -> str:
        text = str(messages)
        if "verdict" in text:
            return '{"verdict": "accept", "issues": []}'
        return GOOD_SQL if "Reviewer feedback" in text else "```sql\nSELECT 1\n```"

    return ScriptedLLM([weak], name="weak")


async def test_study_runs_and_reports_the_effect_of_each_swap() -> None:
    experiment = ExperimentConfig.model_validate({
        "name": "study", "scenarios": ["reflection_sql"], "task_ids": ["harborview_march_rentals"],
        "presets": {"weak": WEAK.model_dump()},
        "study": {"baseline": "weak", "candidates": ["strong"], "roles": ["critic"]},
    })  # fmt: skip
    store = MemoryStore()
    runner = ExperimentRunner(experiment, Runtime(client_factory=factory), store=store, model_specs=SPECS)
    runner.plan()
    assert [c.name for c in runner.experiment.configs] == ["baseline", "critic→strong"]
    await runner.run()
    (effect,) = summarize(store.load_run()).replacements
    assert (effect.role, effect.candidate, effect.tasks, effect.baseline) == ("critic", "strong", 1, "baseline")
    assert effect.baseline_rate == 0.0 and effect.variant_rate == 1.0 and effect.delta == 1.0

    # Runs from before compare_to: the study's tags alone still pair each swap with the baseline.
    data = store.load_run()
    config = json.loads(data.run["config_json"])
    for entry in config["configs"]:
        entry.pop("compare_to", None)
    old = replace(data, run={**data.run, "config_json": json.dumps(config)})
    (legacy,) = summarize(old).replacements
    assert (legacy.role, legacy.baseline, legacy.delta) == ("critic", "baseline", 1.0)


def _compared(**anchor: object) -> ExperimentConfig:
    return ExperimentConfig.model_validate({
        "name": "pair", "scenarios": ["reflection_sql"], "task_ids": ["harborview_march_rentals"],
        "configs": [{"name": "anchor", "roles": {"*": "weak"}},
                    {"name": "strong critic", "roles": {"*": "weak", "critic": "strong"}, **anchor}],
    })  # fmt: skip


async def test_any_configuration_is_compared_with_the_baseline_it_names() -> None:
    store = MemoryStore()
    runner = ExperimentRunner(_compared(compare_to="anchor"), Runtime(client_factory=factory), store=store,
                              model_specs=SPECS)  # fmt: skip
    await runner.run()
    (effect,) = summarize(store.load_run()).replacements
    assert (effect.config, effect.baseline, effect.role, effect.candidate) == ("strong critic", "anchor", "", "")
    assert effect.delta == 1.0

    # Renaming the baseline keeps the comparison.
    renamed, _ = rename_data(store.load_run(), RenameRun(configs={"anchor": "weak everywhere"}))
    (effect,) = summarize(renamed).replacements
    assert effect.baseline == "weak everywhere"

    # Without compare_to there is nothing to compare with.
    plain = MemoryStore()
    await ExperimentRunner(_compared(), Runtime(client_factory=factory), store=plain, model_specs=SPECS).run()
    assert summarize(plain.load_run()).replacements == []


@pytest.mark.parametrize("target", ["strong critic", "missing"])
def test_compare_to_must_name_another_configuration(target: str) -> None:
    with pytest.raises(ValueError, match="compare_to must name another configuration"):
        _compared(compare_to=target)


def test_candidates_only_replace_steps_they_can_do() -> None:
    experiment = ExperimentConfig.model_validate({
        "name": "vision", "scenarios": ["chart_codegen"], "limit": 1, "presets": {"weak": WEAK.model_dump()},
        "study": {"baseline": "weak", "candidates": ["strong"]},
    })  # fmt: skip
    specs = {
        **SPECS,
        "weak": SPECS["weak"].model_copy(
            update={"capabilities": SPECS["weak"].capabilities.model_copy(update={"vision": True})}
        ),
    }
    runner = ExperimentRunner(experiment, Runtime(client_factory=factory), model_specs=specs)
    runner.plan()
    # "strong" has no vision: it may replace the code generator but not the vision critic.
    assert [c.name for c in runner.experiment.configs] == ["baseline", "generator→strong"]


async def test_errors_are_reported_with_the_effect() -> None:
    def out_of_credits(messages: object) -> str:
        raise RuntimeError("no credits remaining")

    def broken(spec: ModelSpec) -> LLMClient:
        return ScriptedLLM([out_of_credits], name="strong") if spec.name == "strong" else factory(spec)

    experiment = ExperimentConfig.model_validate({
        "name": "err", "scenarios": ["reflection_sql"], "task_ids": ["harborview_march_rentals"],
        "presets": {"weak": WEAK.model_dump()}, "study": {"baseline": "weak", "candidates": ["strong"], "roles": ["critic"]},
    })  # fmt: skip
    store = MemoryStore()
    await ExperimentRunner(experiment, Runtime(client_factory=broken), store=store, model_specs=SPECS).run()
    (effect,) = summarize(store.load_run()).replacements
    assert effect.errors == 1 and effect.tasks == 1
