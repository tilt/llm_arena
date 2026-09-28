"""Cross-run leaderboards pool only comparable trials."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.llm.spec import ModelSpec
from llm_arena.report.leaderboard import build_leaderboards
from llm_arena.runner.fingerprint import fingerprint, setup_of


def trial(
    run: str, config: str, task: str, passed: bool, fp: str = "aaa", version: str = "1", **extra: Any
) -> dict[str, Any]:
    return {"run_id": run, "scenario": "s", "config": config, "task_id": task, "task_fp": "t", "passed": passed,
            "status": "ok", "fingerprint": fp, "scenario_version": version, "setup_json": "{}", "cost_usd": 0.01,
            "prompt_tokens": 10, "completion_tokens": 5, "duration_s": 1.0, **extra}  # fmt: skip


def test_runs_pool_by_fingerprint_not_by_name() -> None:
    rows = [
        trial("r1", "old-name", "t1", True), trial("r2", "new-name", "t2", False),  # same setup, renamed
        trial("r2", "other", "t1", False, fp="bbb"), trial("r2", "other", "t2", False, fp="bbb"),
    ]  # fmt: skip
    (board,) = build_leaderboards(rows)
    first, second = board.entries
    assert (first.fingerprint, first.config, first.names, first.runs) == (
        "aaa",
        "new-name",
        ["new-name", "old-name"],
        ["r1", "r2"],
    )
    assert first.pass_rate == 0.5 and first.tasks == 2
    assert second.rank == 2 and second.shared_tasks == 2 and second.delta_vs_leader == -0.5


def test_each_task_weighs_the_same_and_versions_never_mix() -> None:
    rows = [trial("r1", "c", "t1", True) for _ in range(4)] + [trial("r1", "c", "t2", False)]
    rows.append(trial("r3", "c", "t1", False, version="2"))
    rows.append(trial("r3", "c", "t1", False, status="budget"))  # stopped by the spend limit: excluded
    v1, v2 = build_leaderboards(rows)
    assert (v1.scenario_version, v1.entries[0].pass_rate, v1.entries[0].trials) == ("1", 0.5, 5)
    assert (v2.scenario_version, v2.entries[0].trials) == ("2", 1)


def test_edited_tasks_count_as_different_tasks() -> None:
    rows = [trial("r1", "c", "t1", True), trial("r2", "c", "t1", False, task_fp="changed")]
    assert build_leaderboards(rows)[0].entries[0].tasks == 2


def test_legacy_runs_stay_apart_per_config() -> None:
    legacy = {
        "fingerprint": None,
        "scenario_version": None,
        "setup_json": None,
        "roles_json": '{"agent": "m"}',
        "params_json": "{}",
    }
    rows = [trial("r0", "agent-decides", "t1", True, **legacy), trial("r0", "rules-gate", "t1", False, **legacy)]
    (board,) = build_leaderboards(rows)
    assert board.scenario_version == "legacy" and len(board.entries) == 2


def test_fingerprint_covers_call_settings_and_policy() -> None:
    fast = ModelSpec(name="a", provider="ollama", model="qwen3:4b", reasoning_effort="none")
    slow = ModelSpec(name="b", provider="ollama", model="qwen3:4b")
    renamed = ModelSpec(name="c", provider="ollama", model="qwen3:4b", reasoning_effort="none", timeout_s=9)
    fp = lambda spec, decisions=None: fingerprint(setup_of({"agent": spec}, {"max_turns": 10}, decisions))  # noqa: E731
    assert fp(fast) != fp(slow)  # thinking on/off changes results
    assert fp(fast) == fp(renamed)  # alias name and timeouts do not
    assert fp(fast) != fp(fast, {"policy": "rules"})


async def test_duckdb_runs_record_fingerprints_and_feed_the_leaderboard(tmp_path: Path) -> None:
    from llm_arena.runner.ports import Runtime
    from llm_arena.runner.run import ExperimentRunner
    from llm_arena.service import ArenaService
    from test_control import SPECS, _experiment, _factory

    for run_id in ("run-a", "run-b"):
        store = DuckDBStore(tmp_path / run_id)
        await ExperimentRunner(_experiment({"policy": "rules", "control": "gate"}), Runtime(client_factory=_factory),
                               store=store, model_specs=SPECS, run_id=run_id).run()  # fmt: skip
    service = ArenaService(
        Runtime(client_factory=_factory), store_factory=lambda run_id: DuckDBStore(tmp_path / run_id)
    )
    (board,) = service.leaderboards(["run-a", "run-b"])
    assert board.scenario == "support_desk" and board.scenario_version == "1"
    assert [(e.trials, len(e.runs)) for e in board.entries] == [(2, 2), (2, 2)]
    assert {e.setup["decisions"]["policy"] if e.setup["decisions"] else None for e in board.entries} == {"rules", None}
    assert all(set(e.setup["roles"]) == {"agent"} for e in board.entries)  # rules use no decider model


def test_unused_decision_roles_are_not_part_of_the_setup() -> None:
    from llm_arena.decisions.config import DecisionConfig

    assert DecisionConfig(policy="rules").llm_roles() == set()
    assert DecisionConfig(policy="llm").llm_roles() == {"decider"}
    assert DecisionConfig(policy="cascade", primary="ollaya", fallback="llm").llm_roles() == {"escalation"}
