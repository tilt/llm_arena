"""Leaderboards across runs: pool every comparable trial per scenario version and config fingerprint.

Pooling rules (see runner/fingerprint.py):
- trials are grouped by scenario, scenario version and setup fingerprint, never by config name;
- a task is identified by its id *and* content hash, so edited tasks count as different tasks;
- each task weighs the same: pass rate = mean over tasks of the per-task pass share, whatever the
  number of repeats; the 95% CI bootstraps over tasks;
- entries rank by (passes + 1) / (tasks + 2): the pass rate shrunk towards 50% by the amount of
  evidence, so 1 of 1 task (0.67) ranks below 3 of 3 (0.80); ties break by partial credit (eval/credit.py),
  then by cost;
- partial credit and the per-criterion breakdown weigh tasks like the pass rate; errors and timeouts count as
  failing every criterion of their task; trials stored without credit are left out of them;
- comparisons with the leader use only the tasks both have run (paired permutation test).

Trials stopped by a spend limit are excluded (they never ran); errors and timeouts count as fails,
as in a run report. Runs from before fingerprints existed are grouped as `legacy` and never mix
with versioned results.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from llm_arena.eval.metrics import bootstrap_ci, mean, paired_permutation_test, percentile

LEGACY_VERSION = "legacy"


class TrialResult(BaseModel):
    """One trial behind an entry, so a leaderboard can link straight into its run and step inspector."""

    task_id: str
    repeat: int
    passed: bool
    status: str
    run_id: str
    trial_id: str
    credit: float | None = Field(default=None, description="partial credit: share of the graded work done")


class CriterionResult(BaseModel):
    """One pass criterion of an entry: how often it passed and how much of it was met, both averaged over tasks
    (errors and timeouts count as failed)."""

    name: str
    pass_rate: float
    credit: float


class LeaderboardEntry(BaseModel):
    rank: int
    fingerprint: str
    config: str = Field(description="name of the config in its latest run")
    names: list[str] = Field(description="every name this setup ran under")
    setup: dict[str, Any] = Field(description="roles (model + call settings), params and control policy")
    runs: list[str]
    trials: int
    tasks: int
    pass_rate: float = Field(description="mean over tasks of the per-task pass share")
    score: float = Field(
        default=0.0, description="ranking score: pass rate adjusted for the number of tasks, (passes + 1) / (tasks + 2)"
    )
    ci_low: float
    ci_high: float
    credit: float | None = Field(
        default=None, description="partial credit: mean over tasks of the share of graded work done; breaks rank ties"
    )
    criteria: list[CriterionResult] = Field(default_factory=list, description="per pass criterion, in scenario order")
    mean_cost_usd: float
    mean_tokens: float
    latency_p50_s: float
    shared_tasks: int | None = Field(default=None, description="tasks shared with the leader")
    delta_vs_leader: float | None = Field(default=None, description="pass-rate difference on the shared tasks")
    p_vs_leader: float | None = Field(default=None, description="paired permutation test on the shared tasks")
    results: list[TrialResult] = Field(default_factory=list, description="every trial, by task, then run and repeat")


class Leaderboard(BaseModel):
    scenario: str
    scenario_version: str
    tasks: int = Field(description="distinct tasks run by any entry")
    entries: list[LeaderboardEntry]


def build_leaderboards(trials: list[dict[str, Any]], scenario: str | None = None) -> list[Leaderboard]:
    """`trials`: trial rows of any number of runs (each with its `run_id`)."""
    groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for trial in trials:
        if trial.get("status") == "budget" or (scenario and trial["scenario"] != scenario):
            continue
        version = trial.get("scenario_version") or LEGACY_VERSION
        groups[(trial["scenario"], version)][_fingerprint(trial)].append(trial)
    boards = []
    for (name, version), by_fp in sorted(groups.items()):
        applicable = _task_criteria([row for rows in by_fp.values() for row in rows])
        entries = sorted(
            (_entry(fp, rows, applicable) for fp, rows in by_fp.items()),
            key=lambda e: (-e.score, -(e.credit or 0.0), e.mean_cost_usd),
        )
        per_task = {e.fingerprint: _per_task(by_fp[e.fingerprint]) for e in entries}
        leader = per_task[entries[0].fingerprint]
        for rank, entry in enumerate(entries, start=1):
            entry.rank = rank
            if rank > 1:
                shared = sorted(set(leader) & set(per_task[entry.fingerprint]))
                entry.shared_tasks = len(shared)
                if shared:
                    a = [leader[t] for t in shared]
                    b = [per_task[entry.fingerprint][t] for t in shared]
                    entry.delta_vs_leader = mean(b) - mean(a)
                    entry.p_vs_leader = paired_permutation_test(a, b)
        all_tasks = {task for rows in by_fp.values() for task in _per_task(rows)}
        boards.append(Leaderboard(scenario=name, scenario_version=version, tasks=len(all_tasks), entries=entries))
    return boards


def _fingerprint(trial: dict[str, Any]) -> str:
    if trial.get("fingerprint"):
        return str(trial["fingerprint"])
    # Before fingerprints, trials did not record their control policy: the config name is the only hint, so
    # legacy entries merge only when name, models and parameters all match.
    legacy = f"{trial['config']}|{trial.get('roles_json', '')}|{trial.get('params_json', '')}"
    return "legacy-" + hashlib.sha1(legacy.encode()).hexdigest()[:8]


def _setup(trial: dict[str, Any]) -> dict[str, Any]:
    if trial.get("setup_json"):
        return dict(json.loads(trial["setup_json"]))
    return {
        "roles": json.loads(trial.get("roles_json") or "{}"),
        "params": json.loads(trial.get("params_json") or "{}"),
    }


def _task_key(trial: dict[str, Any]) -> str:
    return f"{trial['task_id']}@{trial.get('task_fp') or ''}"


def _per_task(rows: list[dict[str, Any]]) -> dict[str, float]:
    outcomes: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        outcomes[_task_key(row)].append(float(bool(row["passed"])))
    return {task: mean(values) for task, values in outcomes.items()}


def _credit(row: dict[str, Any]) -> float | None:
    value = row.get("credit")
    if value is None or not row.get("criteria_json") or math.isnan(float(value)):
        return None  # stored before partial credit existed
    return float(value)


def _task_mean(values: dict[str, list[float]]) -> float | None:
    """Mean over tasks of each task's mean (every task weighs the same); None without values."""
    per_task = [mean(v) for v in values.values() if v]
    return mean(per_task) if per_task else None


def _task_criteria(rows: list[dict[str, Any]]) -> Callable[[str], list[str]]:
    """The pass criteria that apply to each task, learned from the board's graded trials.

    Some criteria apply to some tasks only (an answer check for questions), so an errored trial is charged with the
    criteria its task's graded trials had, or, for a task no setup ran without error, with those every task had.
    """
    by_task: dict[str, list[str]] = {}
    for row in rows:
        if row.get("status") == "ok" and _credit(row) is not None:
            by_task.setdefault(_task_key(row), list(json.loads(row["criteria_json"])))
    sets = [set(names) for names in by_task.values()]
    common = [name for name in next(iter(by_task.values()), []) if all(name in names for names in sets)]
    return lambda task: by_task.get(task, common)


def _criteria(rows: list[dict[str, Any]], applicable: Callable[[str], list[str]]) -> list[CriterionResult]:
    passes: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    credits: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("status") != "ok":
            # Errors and timeouts fail every criterion of their task, as they fail the pass rate.
            results = {name: {"passed": False, "credit": 0.0} for name in applicable(_task_key(row))}
        elif _credit(row) is not None:
            results = json.loads(row["criteria_json"])
        else:
            continue  # stored before partial credit
        for name, result in results.items():
            passes[name][_task_key(row)].append(float(bool(result["passed"])))
            credits[name][_task_key(row)].append(float(result["credit"]))
    return [
        CriterionResult(name=name, pass_rate=_task_mean(passes[name]) or 0.0, credit=_task_mean(credits[name]) or 0.0)
        for name in passes
    ]


def _entry(fp: str, rows: list[dict[str, Any]], applicable: Callable[[str], list[str]]) -> LeaderboardEntry:
    latest = max(rows, key=lambda r: str(r.get("run_id", "")))
    per_task = list(_per_task(rows).values())
    pass_rate, low, high = bootstrap_ci(per_task)
    # Laplace-adjusted: one lucky task must not outrank a setup that passed most of many tasks.
    score = (sum(per_task) + 1) / (len(per_task) + 2)
    credits: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if (value := _credit(row)) is not None:
            credits[_task_key(row)].append(value)
    return LeaderboardEntry(
        rank=0,
        fingerprint=fp,
        config=str(latest["config"]),
        names=sorted({str(r["config"]) for r in rows}),
        setup=_setup(latest),
        runs=sorted({str(r.get("run_id", "")) for r in rows}),
        trials=len(rows),
        tasks=len(per_task),
        pass_rate=pass_rate,
        score=score,
        ci_low=low,
        ci_high=high,
        credit=_task_mean(credits),
        criteria=_criteria(rows, applicable),
        mean_cost_usd=mean([float(r.get("cost_usd") or 0.0) + float(r.get("judge_cost_usd") or 0.0) for r in rows]),
        mean_tokens=mean([float((r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0)) for r in rows]),
        latency_p50_s=percentile(sorted(float(r.get("duration_s") or 0.0) for r in rows), 0.5),
        results=[
            TrialResult(
                task_id=str(r["task_id"]),
                repeat=int(r.get("repeat") or 0),
                passed=bool(r["passed"]),
                status=str(r.get("status", "ok")),
                run_id=str(r.get("run_id", "")),
                trial_id=str(r.get("trial_id", "")),
                credit=_credit(r),
            )
            for r in sorted(
                rows, key=lambda r: (str(r["task_id"]), str(r.get("run_id", "")), int(r.get("repeat") or 0))
            )
        ],  # fmt: skip
    )
