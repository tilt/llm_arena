"""Re-grading stored trials of an earlier, grading-only scenario version into the current one (runner/regrade.py)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import duckdb
import pytest

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.testing import ScriptedLLM, tool_call
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.fingerprint import resume_key
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.runner.regrade import regrade_run
from llm_arena.runner.run import ExperimentRunner
from llm_arena.scenarios.base import get_scenario
from llm_arena.service import ArenaService

SPECS = {"m": ModelSpec(name="m", provider="openai_compatible", model="m")}
CURRENT = get_scenario("support_desk").version
OLD = sorted(get_scenario("support_desk").regrades_from)[0]
EXPERIMENT = ExperimentConfig.model_validate({
    "name": "old", "scenarios": ["support_desk"], "task_ids": ["damaged_2001", "damaged_2005"], "seed": 7,
    "configs": [{"name": "agent", "roles": {"*": "m"}}],
})  # fmt: skip


def _silent(spec: ModelSpec) -> LLMClient:
    """Refunds without messaging the customer. Fresh per call, so both tasks see the same script: damaged_2001 gets
    the right refund (credit 2/3), damaged_2005 a wrong one (credit 1/3)."""
    return ScriptedLLM([tool_call("issue_refund", order_id=2001, amount=24.0, reason="damaged"), "Refunded."])


async def _old_run(store: Any) -> None:
    """A run as an earlier version recorded it: old version and resume key, no credit, binary scores."""
    await ExperimentRunner(EXPERIMENT, Runtime(client_factory=_silent), store=store, model_specs=SPECS,
                           run_id="r").run()  # fmt: skip
    for row in store.load_run().trials:
        seed = EXPERIMENT.seed + row["repeat"]
        old = {"scenario_version": OLD, "credit": None, "criteria_json": None,
               "resume_key": resume_key(row["fingerprint"], OLD, row["task_fp"], seed)}  # fmt: skip
        if isinstance(store, MemoryStore):
            store.trials[row["trial_id"]].update(old)
            store.scores[row["trial_id"]] += [
                {"trial_id": row["trial_id"], "name": "quality", "level": "e2e", "value": 0.5, "passed": True,
                 "rationale": "judge"},
                {"trial_id": row["trial_id"], "name": "retired_metric", "level": "step", "value": 1.0, "passed": None,
                 "rationale": "no evaluator emits this any more"},
            ]  # fmt: skip
        else:
            with duckdb.connect(str(store.path)) as db:
                db.execute("UPDATE trials SET scenario_version = ?, credit = NULL, criteria_json = NULL, "
                           "resume_key = ? WHERE trial_id = ?", [OLD, old["resume_key"], row["trial_id"]])  # fmt: skip


class _StubJudge:
    """Stands in for a rubric judge: owns the `quality` scores and, without a judge model, produces none."""

    name = "judge:quality"

    def owns(self, score_name: str) -> bool:
        return score_name == "quality" or score_name.startswith("quality.")

    async def evaluate(self, ctx: Any) -> list[Any]:
        return []


@pytest.fixture
def with_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = type(get_scenario("support_desk"))
    evaluators = scenario.evaluators
    monkeypatch.setattr(scenario, "evaluators", lambda self, params: [*evaluators(self, params), _StubJudge()])


async def test_regrade_moves_trials_to_the_current_version_and_keeps_judge_scores(with_judge: None) -> None:
    store = MemoryStore()
    await _old_run(store)
    service = ArenaService(Runtime(client_factory=_silent), store_factory=lambda _: store)
    (dry,) = await service.regrade(["r"])
    assert dry.summary() == {("support_desk", OLD, CURRENT): (2, 0, 0)}
    assert {row["scenario_version"] for row in store.load_run().trials} == {OLD}  # a dry run writes nothing

    await service.regrade(["r"], apply=True)
    data = store.load_run()
    assert {row["scenario_version"] for row in data.trials} == {CURRENT}
    assert {row["task_id"]: row["credit"] for row in data.trials} == {"damaged_2001": 2 / 3, "damaged_2005": 1 / 3}
    assert not any(row["passed"] for row in data.trials)
    names = {score["name"] for score in data.scores}
    assert {"state_correct", "customer_informed", "quality"} <= names  # the judge score was carried over
    assert "retired_metric" not in names  # only scores a judge owns are carried over
    trace = store.load_trace(data.trials[0]["trial_id"]) or {}
    assert trace["extra"]["regraded"] == {"from_version": OLD, "passed_before": False}
    assert trace["trial"]["scenario_version"] == CURRENT and trace["trial"]["credit"] == data.trials[0]["credit"]

    (board,) = service.leaderboards(["r"])
    assert board.scenario_version == CURRENT and board.entries[0].credit == 0.5
    (again,) = await service.regrade(["r"])
    assert not again.trials and again.skipped == {f"support_desk {CURRENT}: already current": 2}


async def test_regraded_runs_resume_without_rerunning(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "r")
    await _old_run(store)
    service = ArenaService(Runtime(client_factory=_silent), store_factory=lambda _: DuckDBStore(tmp_path / "r"))
    await service.regrade(["r"], apply=True)
    await ExperimentRunner(EXPERIMENT, Runtime(client_factory=_silent), store=DuckDBStore(tmp_path / "r"),
                           model_specs=SPECS, run_id="r").run()  # fmt: skip
    # The resume keys follow the new version, so every finished trial was skipped, not rerun (a rerun would
    # rewrite its trace without the re-grade note).
    for path in (tmp_path / "r" / "traces").glob("*.json"):
        trace = json.loads(path.read_text(encoding="utf-8"))
        assert trace["trial"]["scenario_version"] == CURRENT and "regraded" in trace["extra"]


async def test_trials_that_cannot_be_regraded_keep_their_version() -> None:
    store = MemoryStore()
    await _old_run(store)
    rows = sorted(store.trials)
    store.trials[rows[0]]["task_fp"] = "edited"
    store.traces.pop(rows[1])
    report = await regrade_run("r", store.load_run(), store.load_trace, store.load_artifact)
    assert not report.trials
    assert report.skipped == {f"support_desk {OLD}: task changed since": 1, f"support_desk {OLD}: trace missing": 1}

    for row in store.trials.values():
        row.update(scenario_version="0", task_fp=store.trials[rows[1]]["task_fp"])
    report = await regrade_run("r", store.load_run(), store.load_trace, store.load_artifact)
    assert set(report.skipped) == {f"support_desk 0: prompts, tools or tasks differ from version {CURRENT}"}
    for row in store.trials.values():
        row.update(scenario_version=None, fingerprint=None)
    report = await regrade_run("r", store.load_run(), store.load_trace, store.load_artifact)
    assert set(report.skipped) == {"support_desk: recorded before scenario versions (legacy board)"}


async def test_result_files_must_still_be_there() -> None:
    store = MemoryStore()
    await _old_run(store)
    trial_id = sorted(store.trials)[0]
    store.traces[trial_id]["spans"].append(
        {"kind": "step", "name": "result", "artifacts": [{"name": "chart.png", "media_type": "image/png", "size": 1}]}
    )  # a file that was never stored (size limit): the evaluators would see a different output
    report = await regrade_run("r", store.load_run(), store.load_trace, store.load_artifact)
    assert report.skipped == {f"support_desk {OLD}: result files missing": 1} and len(report.trials) == 1


async def test_old_grading_never_fills_in_for_a_failing_evaluator() -> None:
    store = MemoryStore()
    await _old_run(store)
    for trace in store.traces.values():
        trace["extra"].pop("env_state")  # the current evaluator cannot grade this trial
    report = await regrade_run("r", store.load_run(), store.load_trace, store.load_artifact)
    assert not report.trials
    assert report.skipped == {f"support_desk {OLD}: current evaluators failed (desk_state.error)": 2}


async def test_a_failed_database_write_leaves_traces_and_rows_untouched(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "r")
    await _old_run(store)
    before = {path.name: path.read_text(encoding="utf-8") for path in (tmp_path / "r" / "traces").glob("*")}
    report = await regrade_run("r", store.load_run(), store.load_trace, store.load_artifact)
    broken = [replace(report.trials[0], columns={**report.trials[0].columns, "credit": "not a number"})]
    with pytest.raises(duckdb.Error):
        store.regrade([*report.trials[1:], *broken])
    after = {path.name: path.read_text(encoding="utf-8") for path in (tmp_path / "r" / "traces").glob("*")}
    assert after == before  # no trace swapped in, no staged file left behind
    assert {row["scenario_version"] for row in store.load_run().trials} == {OLD}  # rolled back
