"""Partial credit: the per-trial share of graded work, its backfill for old runs, and where it shows up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.eval.base import Score
from llm_arena.eval.credit import change_credit, share, trial_credit, with_credit
from llm_arena.report.aggregate import summarize
from llm_arena.report.leaderboard import build_leaderboards
from llm_arena.runner.ports import RunData


def _score(name: str, value: float, passed: bool | None) -> Score:
    return Score(name=name, value=value, level="e2e", passed=passed)


def test_trial_credit_is_the_mean_criterion_credit_and_one_only_when_passed() -> None:
    scores = [
        _score("state", 0.5, False),
        _score("safe", 1.0, True),
        _score("extra", 0.0, None),
        _score("f1", 0.2, True),
    ]
    credit, detail = trial_credit("ok", scores, ["state", "safe", "extra", "missing"])
    assert credit == 0.75  # extra is ungraded and missing was not produced: neither counts
    assert detail == {"state": {"credit": 0.5, "passed": False}, "safe": {"credit": 1.0, "passed": True}}
    # A passed criterion earns full credit even when its value is a rate below 1 (fact_recall >= 0.75 passes).
    assert trial_credit("ok", [_score("recall", 0.8, True)], ["recall"])[0] == 1.0
    # A failed criterion never looks complete: a value of 1 or more (or below 0) is no share, so it earns nothing.
    for value in (1.0, 7.0, -0.5, float("nan")):
        assert trial_credit("ok", [_score("state", value, False)], ["state"])[0] == 0.0
    assert trial_credit("error", scores, ["state", "safe"]) == (0.0, {})
    assert trial_credit("ok", [], ["state"]) == (0.0, {})


def test_change_credit_rewards_needed_work_and_charges_breakage() -> None:
    before = {"a": False, "b": False, "kept": True}
    assert change_credit(before, {"a": False, "b": False, "kept": True}) == 0.0  # doing nothing
    assert change_credit(before, {"a": True, "b": False, "kept": True}) == 0.5
    assert change_credit(before, {"a": True, "b": True, "kept": False}) == 2 / 3  # done, but broke what was fine
    assert change_credit({"kept": True}, {"kept": True}) == 1.0  # nothing to do, nothing broken
    assert change_credit({}, {"new": False}) == 0.0  # a key unknown before counts as met, so failing it is breakage
    assert share({"a": True, "b": False}) == 0.5 and share({}) == 1.0


def _row(trial_id: str, task: str, passed: bool, credit: float | None, fp: str = "aaa", **extra: Any) -> dict[str, Any]:
    row = {"run_id": "r", "trial_id": trial_id, "scenario": "s", "config": fp, "task_id": task, "task_fp": "t",
           "passed": passed, "status": "ok", "fingerprint": fp, "scenario_version": "1", "setup_json": "{}",
           "cost_usd": 0.01, "prompt_tokens": 1, "completion_tokens": 1, "duration_s": 1.0, **extra}  # fmt: skip
    if credit is not None:
        row["credit"] = credit
        row["criteria_json"] = json.dumps({"state": {"credit": credit, "passed": passed},
                                           "safe": {"credit": 1.0, "passed": True}})  # fmt: skip
    return row


def test_leaderboard_breaks_ties_by_credit_and_breaks_down_criteria() -> None:
    rows = [
        _row("1", "t1", False, 0.2, fp="low"), _row("2", "t2", False, 0.2, fp="low"),
        _row("3", "t1", False, 0.9, fp="high"), _row("4", "t2", False, 0.5, fp="high"),
        _row("5", "t1", False, 0.7, fp="high"),  # a repeat: t1 averages 0.8 before tasks are averaged
    ]  # fmt: skip
    (board,) = build_leaderboards(rows)
    assert [e.fingerprint for e in board.entries] == ["high", "low"]  # both 0%, high did more of the work
    high = board.entries[0]
    assert high.pass_rate == 0.0 and abs((high.credit or 0) - 0.65) < 1e-9
    assert [(c.name, c.pass_rate) for c in high.criteria] == [("state", 0.0), ("safe", 1.0)]
    assert {r.trial_id: r.credit for r in high.results} == {"3": 0.9, "5": 0.7, "4": 0.5}


def test_errors_fail_the_criteria_of_their_task_in_the_breakdown() -> None:
    def graded(trial_id: str, task: str, fp: str, criteria: dict[str, bool]) -> dict[str, Any]:
        detail = {name: {"credit": float(ok), "passed": ok} for name, ok in criteria.items()}
        return _row(trial_id, task, all(criteria.values()), 1.0, fp=fp) | {"criteria_json": json.dumps(detail)}

    def errored(trial_id: str, task: str, fp: str) -> dict[str, Any]:
        return _row(trial_id, task, False, 0.0, fp=fp, status="error") | {"criteria_json": "{}"}

    rows = [
        graded("1", "chore", "a", {"state": True}), errored("2", "question", "a"), errored("3", "new", "a"),
        graded("4", "question", "b", {"state": True, "answer": True}), graded("5", "chore", "b", {"state": True}),
    ]  # fmt: skip
    (board,) = build_leaderboards(rows)
    flaky = next(e for e in board.entries if e.fingerprint == "a")
    # "question" errored, so both its criteria (known from setup b) fail; "new" never ran anywhere, so it is charged
    # with the criterion every task has. The breakdown no longer looks healthier than the pass rate.
    assert {c.name: c.pass_rate for c in flaky.criteria} == {"state": 1 / 3, "answer": 0.0}


def test_rows_without_credit_leave_it_unknown() -> None:
    (board,) = build_leaderboards([_row("1", "t1", True, None), _row("2", "t2", False, None)])
    entry = board.entries[0]
    assert entry.credit is None and entry.criteria == [] and entry.results[0].credit is None


def test_old_runs_get_credit_from_their_scores() -> None:
    trials = [_row("a", "t1", False, None, status="ok"), _row("b", "t1", False, None, status="error"),
              _row("c", "t1", False, None, scenario="gone")]  # fmt: skip
    scores = [
        {"trial_id": "a", "name": "state_correct", "level": "e2e", "value": 0.0, "passed": False},
        {"trial_id": "a", "name": "customer_informed", "level": "e2e", "value": 1.0, "passed": True},
        {"trial_id": "a", "name": "policy_compliant", "level": "e2e", "value": 1.0, "passed": True},
        {"trial_id": "a", "name": "human_reviews", "level": "step", "value": 3.0, "passed": None},
    ]
    criteria = {"s": ["state_correct", "customer_informed", "policy_compliant"]}
    filled = with_credit(trials, scores, criteria.get)
    assert filled[0]["credit"] == 2 / 3 and list(json.loads(filled[0]["criteria_json"])) == criteria["s"]
    assert filled[1]["credit"] == 0.0  # errors earn nothing
    assert "credit" not in filled[2]  # unknown scenario: left without credit
    credited = filled[:2]
    assert with_credit(credited, scores, criteria.get) is credited  # rows that have credit are kept as they are


def test_backfill_leaves_credit_unknown_when_it_contradicts_the_stored_verdict() -> None:
    # Graded by a version whose extra pass criterion failed; today's criteria all passed, which would read 100%.
    trial = _row("a", "t1", False, None)
    scores = [{"trial_id": "a", "name": n, "level": "e2e", "value": v, "passed": bool(v)}
              for n, v in (("state_correct", 1.0), ("retired_gate", 0.0))]  # fmt: skip
    (row,) = with_credit([trial], scores, lambda _: ["state_correct"])
    assert "credit" not in row and not row.get("criteria_json")


def test_run_summary_backfills_credit_from_the_scenario_criteria() -> None:
    trial = {"trial_id": "a", "run_id": "r", "scenario": "support_desk", "pattern": "p", "config": "c", "task_id": "t",
             "repeat": 0, "status": "ok", "passed": False, "duration_s": 1.0, "prompt_tokens": 1,
             "completion_tokens": 1, "cost_usd": 0.0, "judge_cost_usd": 0.0, "roles_json": "{}"}  # fmt: skip
    scores = [{"trial_id": "a", "name": n, "level": "e2e", "value": v, "passed": bool(v)}
              for n, v in (("state_correct", 1.0), ("customer_informed", 0.0), ("policy_compliant", 1.0))]  # fmt: skip
    (config,) = summarize(RunData(run={}, trials=[trial], scores=scores)).configs
    assert config.pass_rate == 0.0 and config.credit == 2 / 3


def test_duckdb_runs_from_before_credit_gain_the_columns(tmp_path: Path) -> None:
    (tmp_path / "traces").mkdir()
    with duckdb.connect(str(tmp_path / "arena.duckdb")) as db:
        db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, name TEXT, created_at TIMESTAMP, config_json TEXT);"
                   "CREATE TABLE trials (trial_id TEXT PRIMARY KEY, run_id TEXT, scenario TEXT, passed BOOLEAN);")  # fmt: skip
    DuckDBStore(tmp_path)
    with duckdb.connect(str(tmp_path / "arena.duckdb"), read_only=True) as db:
        columns = {row[0] for row in db.execute("SELECT column_name FROM information_schema.columns "
                                                 "WHERE table_name = 'trials'").fetchall()}  # fmt: skip
    assert {"credit", "criteria_json"} <= columns


def test_failed_pass_criteria_report_a_share_below_one() -> None:
    """Graders keep the convention credit relies on: a failed pass criterion's value is a share in [0, 1)."""
    from llm_arena.scenarios.base import get_scenario

    vectors = sorted((Path(__file__).parents[1] / "contracts" / "conformance").glob("*.json"))
    assert vectors
    for path in vectors:
        vector = json.loads(path.read_text(encoding="utf-8"))
        criteria = get_scenario(vector["case"]["scenario"]).pass_criteria
        for name, score in vector["scores"].items():
            if name in criteria and score["passed"] is False:
                assert 0.0 <= score["value"] < 1.0, f"{path.stem}: {name} failed with value {score['value']}"
