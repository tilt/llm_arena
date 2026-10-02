"""Renaming a finished run changes its names everywhere they are shown, and nothing else."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.core.errors import ConfigError
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.runner.rename import RenameRun
from llm_arena.runner.run import ExperimentRunner
from llm_arena.server.app import create_app
from llm_arena.server.keys import KeyStore
from llm_arena.service import ArenaService, rename_bundle
from server_test_client import SESSION_TOKEN, authenticated_client
from test_control import SPECS, _experiment, _factory

GATE = {"policy": "rules", "control": "gate"}


async def _run(store: DuckDBStore | MemoryStore, run_id: str = "run-a") -> None:
    runner = ExperimentRunner(_experiment(GATE), Runtime(client_factory=_factory), store=store, model_specs=SPECS,
                              run_id=run_id)  # fmt: skip
    await runner.run()


def _service(tmp_path: Path) -> ArenaService:
    return ArenaService(Runtime(client_factory=_factory), store_factory=lambda run_id: DuckDBStore(tmp_path / run_id))


async def test_duckdb_rename_relabels_rows_traces_and_leaderboard(tmp_path: Path) -> None:
    await _run(DuckDBStore(tmp_path / "run-a"))
    service = _service(tmp_path)
    before = service.leaderboards(["run-a"])[0].entries
    # Swapping two names in one go must work (no intermediate clash).
    service.rename_run("run-a", RenameRun(name="gate study", configs={"agent": "rules", "rules": "agent"}))

    data = DuckDBStore(tmp_path / "run-a").load_run()
    assert data.run["name"] == "gate study" and json.loads(data.run["config_json"])["name"] == "gate study"
    assert [c["name"] for c in json.loads(data.run["config_json"])["configs"]] == ["rules", "agent"]
    by_trial = {t["trial_id"]: t["config"] for t in data.trials}
    assert {d["config"] for d in data.decisions} == {by_trial[d["trial_id"]] for d in data.decisions}
    for trial_id, config in by_trial.items():  # ids stay; traces follow the new names
        assert json.loads((tmp_path / "run-a" / "traces" / f"{trial_id}.json").read_text())["trial"]["config"] == config

    after = service.leaderboards(["run-a"])[0].entries
    swap = {"agent": "rules", "rules": "agent"}
    assert {(e.fingerprint, e.trials, e.config) for e in after} == {
        (e.fingerprint, e.trials, swap[e.config]) for e in before
    }
    assert {c.config for c in service.run_bundle("run-a").summary.configs} == {"agent", "rules"}


async def test_invalid_renames_change_nothing(tmp_path: Path) -> None:
    await _run(DuckDBStore(tmp_path / "run-a"))
    service = _service(tmp_path)
    for request, message in [
        (RenameRun(configs={"nope": "x"}), "no setup named nope"),
        (RenameRun(configs={"agent": "rules"}), "unique"),
        (RenameRun(configs={"agent": "  "}), "cannot be empty"),
        (RenameRun(name=" "), "run name cannot be empty"),
    ]:
        with pytest.raises(ConfigError, match=message):
            service.rename_run("run-a", request)
    assert sorted({t["config"] for t in DuckDBStore(tmp_path / "run-a").load_run().trials}) == ["agent", "rules"]


async def test_browser_bundles_and_this_tabs_store_rename_alike() -> None:
    store = MemoryStore()
    await _run(store)
    service = ArenaService(Runtime(client_factory=_factory), store_factory=lambda _: store)
    bundle = service.run_bundle("run-a")
    renamed = rename_bundle(bundle, RenameRun(name="mine", configs={"rules": "rules-gate"}))
    assert renamed.run["name"] == "mine"
    assert {t["config"] for t in renamed.trials} == {"agent", "rules-gate"}
    assert {c.config for c in renamed.summary.configs} == {"agent", "rules-gate"}  # recomputed, not stale
    assert {d.config for d in renamed.summary.decisions} == {"rules-gate"}
    assert {t["trial"]["config"] for t in renamed.traces.values()} == {"agent", "rules-gate"}

    service.rename_run("run-a", RenameRun(configs={"rules": "rules-gate"}))
    assert {t["config"] for t in store.load_run().trials} == {"agent", "rules-gate"}


async def test_api_renames_finished_runs(tmp_path: Path) -> None:
    await _run(DuckDBStore(tmp_path / "run-a"))
    client = authenticated_client(
        create_app(_service(tmp_path), runs_dir=tmp_path, keys=KeyStore(), session_token=SESSION_TOKEN)
    )
    assert client.patch("/api/runs/run-a", json={"name": "renamed", "configs": {"agent": "solo"}}).status_code == 204
    listing = next(r for r in client.get("/api/runs").json() if r["run_id"] == "run-a")
    assert listing["name"] == "renamed"
    assert {e["config"] for b in client.get("/api/leaderboard").json() for e in b["entries"]} == {"solo", "rules"}
    assert client.patch("/api/runs/run-a", json={"configs": {"solo": "rules"}}).status_code == 400
    assert client.patch("/api/runs/missing", json={"name": "x"}).status_code == 404
