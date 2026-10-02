"""Model presets bind a model per kind of step; explicit bindings win; profiles load, save and serve."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_arena.core.errors import ConfigError
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.runner.config import ExperimentConfig, PipelineConfig
from llm_arena.runner.ports import Runtime
from llm_arena.runner.presets import DEFAULT_PRESETS, ModelPreset, load_presets, save_preset
from llm_arena.runner.run import ExperimentRunner
from server_test_client import SESSION_TOKEN, authenticated_client

# What discovery would report: the vision model can see images (capabilities come from the server).
DISCOVERED = {"ollama:qwen3-vl:8b": ModelSpec(name="ollama:qwen3-vl:8b", provider="ollama", model="qwen3-vl:8b",
                                              capabilities=Capabilities(vision=True))}  # fmt: skip


def _factory(spec: ModelSpec) -> LLMClient:
    return ScriptedLLM(["x"], spec=spec)


def _bindings(config: dict[str, object], scenario: str, **extra: object) -> dict[str, str]:
    experiment = ExperimentConfig.model_validate(
        {"name": "b", "scenarios": [scenario], "limit": 1, "configs": [config], **extra}
    )
    (trial,) = ExperimentRunner(experiment, Runtime(client_factory=_factory), model_specs=DISCOVERED).plan()
    return {role: spec.name for role, spec in trial.bindings.items()}


def test_preset_binds_every_role_by_its_kind() -> None:
    bound = _bindings({"name": "base", "preset": "local-small"}, "chart_codegen")
    assert bound == {"generator": "ollama:qwen3:4b#reasoning=none", "critic": "ollama:qwen3-vl:8b#reasoning=none"}


def test_explicit_bindings_win_over_the_preset() -> None:
    config = {
        "name": "swap",
        "preset": "local-small",
        "scenario_roles": {"reflection_sql": {"critic": "openai:gpt-5-mini"}},
    }
    bound = _bindings(config, "reflection_sql")
    assert bound == {"generator": "ollama:qwen3:4b#reasoning=none", "critic": "openai:gpt-5-mini"}


def test_a_default_model_next_to_a_preset_is_rejected() -> None:
    # The preset fills every unbound role first, so the default would silently never run.
    with pytest.raises(ValueError, match="either a preset"):
        PipelineConfig.model_validate({"name": "x", "preset": "local-small", "roles": {"*": "ollama:qwen3:14b"}})
    assert PipelineConfig.model_validate({"name": "x", "preset": "local-small", "roles": {"*": ""}}).preset


def test_experiment_profiles_override_and_unknown_profiles_fail() -> None:
    mine = {"mine": {"label": "Mine", "models": {"text": "openai:gpt-4.1-nano"}}}
    bound = _bindings({"name": "m", "preset": "mine"}, "reflection_writing", presets=mine)
    assert set(bound.values()) == {"openai:gpt-4.1-nano"}  # kinds missing from the profile use its text model
    with pytest.raises(ConfigError, match="unknown preset"):
        _bindings(
            {"name": "x", "baseline": "nope"}, "reflection_writing"
        )  # `baseline:` is the old name, still accepted


def test_profiles_load_and_save_local_overrides(tmp_path: Path) -> None:
    local = tmp_path / "presets.local.yaml"
    save_preset(local, "tiny", ModelPreset(label="Tiny", models={"text": "ollama:qwen3:0.6b"}))
    save_preset(local, "local-small", ModelPreset(label="Local small (mine)", models={"text": "ollama:qwen3:1.7b"}))
    profiles = load_presets(local)
    assert profiles["tiny"].label == "Tiny" and profiles["local-small"].label == "Local small (mine)"
    assert profiles["openai-mini"] == DEFAULT_PRESETS["openai-mini"]
    save_preset(local, "local-small", None)
    assert load_presets(local)["local-small"] == DEFAULT_PRESETS["local-small"]


def test_preset_api_lists_saves_and_resets(tmp_path: Path) -> None:
    from llm_arena.runner.memory_store import MemoryStore
    from llm_arena.server.app import create_app
    from llm_arena.server.keys import KeyStore
    from llm_arena.service import ArenaService

    service = ArenaService(Runtime(client_factory=_factory), store_factory=lambda _: MemoryStore(),
                           presets_file=tmp_path / "presets.local.yaml")  # fmt: skip
    client = authenticated_client(create_app(service, runs_dir=tmp_path, keys=KeyStore(), session_token=SESSION_TOKEN))
    assert set(client.get("/api/presets").json()) == {"local-small", "openai-mini"}
    profile = {"label": "Tiny", "models": {"text": "ollama:qwen3:0.6b"}}
    assert "tiny" in client.put("/api/presets/tiny", json=profile).json()
    assert client.put("/api/presets/Bad Name", json=profile).status_code == 400
    assert "tiny" not in client.delete("/api/presets/tiny").json()
    assert (tmp_path / "presets.local.yaml").exists()
