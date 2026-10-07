"""Re-grade stored trials with the current evaluators, so runs of an earlier scenario version join the current board.

Only versions a scenario lists in `regrades_from` qualify: they differ from the current one in grading alone (same
prompts, tools and tasks), so what the agent did is still valid evidence and only the verdict is recomputed. Each
trial is re-graded from what it stored: the final output, the environment state and extras, the trace spans and the
files attached to its result step.

A trial keeps its old version (and so stays on the old board) when its task has changed since, or when its trace or
result files are missing, or when a current evaluator fails on it: a verdict is only replaced by a complete new one.
Judge rubric scores need a model and cannot be recomputed offline, so they are carried over from the original
grading. Nothing else is: no pass criterion is ever taken from the old grading. Errored trials have nothing to
grade; they move with their run and still count as fails.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_arena.core.errors import ConfigError
from llm_arena.core.task import Task
from llm_arena.core.trace import Trace
from llm_arena.eval.base import EvalContext, Score, TrialOutput, evaluate_all
from llm_arena.eval.credit import trial_credit, trial_passed
from llm_arena.eval.judge import JudgeEvaluator
from llm_arena.runner.fingerprint import resume_key, task_fingerprint
from llm_arena.runner.ports import RunData
from llm_arena.scenarios.base import Scenario, get_scenario

TraceLoader = Callable[[str], "dict[str, Any] | None"]
ArtifactLoader = Callable[[str], "tuple[bytes, str] | None"]


@dataclass(frozen=True)
class RegradedTrial:
    """One trial's new grading: the trial columns to update, its full score list and its rewritten trace file."""

    trial_id: str
    scenario: str
    from_version: str
    to_version: str
    passed_before: bool
    columns: dict[str, Any]  # scenario_version, passed, credit, criteria_json, resume_key
    scores: list[Score]
    trace: dict[str, Any]


@dataclass
class RegradeReport:
    run_id: str
    trials: list[RegradedTrial] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)  # reason -> trials left as they are

    def summary(self) -> dict[tuple[str, str, str], tuple[int, int, int]]:
        """(scenario, from, to) -> (trials, passed before, passed after)."""
        out: dict[tuple[str, str, str], tuple[int, int, int]] = {}
        for trial in self.trials:
            key = (trial.scenario, trial.from_version, trial.to_version)
            n, before, after = out.get(key, (0, 0, 0))
            out[key] = (n + 1, before + trial.passed_before, after + bool(trial.columns["passed"]))
        return out


async def regrade_run(
    run_id: str, data: RunData, load_trace: TraceLoader, load_artifact: ArtifactLoader
) -> RegradeReport:
    report = RegradeReport(run_id)
    config = json.loads(data.run.get("config_json") or "{}")
    scores_by_trial: dict[str, list[dict[str, Any]]] = {}
    for row in data.scores:
        scores_by_trial.setdefault(str(row["trial_id"]), []).append(row)
    tasks: dict[str, dict[str, Task]] = {}
    for row in data.trials:
        result = await _regrade_trial(row, config, scores_by_trial.get(str(row["trial_id"]), []), tasks,
                                      load_trace, load_artifact)  # fmt: skip
        if isinstance(result, str):
            report.skipped[result] += 1
        else:
            report.trials.append(result)
    return report


async def _regrade_trial(
    row: dict[str, Any],
    config: dict[str, Any],
    old_scores: list[dict[str, Any]],
    tasks: dict[str, dict[str, Task]],
    load_trace: TraceLoader,
    load_artifact: ArtifactLoader,
) -> RegradedTrial | str:
    """The re-graded trial, or why it stays as it is."""
    name, version = str(row["scenario"]), str(row.get("scenario_version") or "")
    try:
        scenario = get_scenario(name)
    except ConfigError:
        return f"{name}: unknown scenario"
    if version == scenario.version:
        return f"{name} {version}: already current"
    if not version or not row.get("fingerprint"):
        # Without a version, setup fingerprint and task hash there is nothing to prove the trial ran the same task.
        return f"{name}: recorded before scenario versions (legacy board)"
    if version not in scenario.regrades_from:
        return f"{name} {version}: prompts, tools or tasks differ from version {scenario.version}"
    try:
        task = _tasks(scenario, tasks).get(str(row["task_id"]))
    except Exception as exc:  # e.g. a benchmark whose dataset cannot be fetched here
        return f"{name} {version}: tasks unavailable ({type(exc).__name__})"
    if task is None or task_fingerprint(task) != row.get("task_fp"):
        return f"{name} {version}: task changed since"
    payload = load_trace(str(row["trial_id"]))
    if payload is None:
        return f"{name} {version}: trace missing"
    status = str(row.get("status") or "ok")
    scores: list[Score] = []
    if status == "ok":
        output = _output(row, payload, load_artifact)
        if output is None:
            return f"{name} {version}: result files missing"
        params = {**scenario.default_params, **json.loads(row.get("params_json") or "{}")}
        trace = Trace.model_validate({"spans": payload.get("spans", [])})
        evaluators = scenario.evaluators(params)
        scores = await evaluate_all(evaluators, EvalContext(task, output, trace, params=params))
        if failed := sorted(score.name for score in scores if score.name.endswith(".error")):
            return f"{name} {version}: current evaluators failed ({', '.join(failed)})"
        # Judge scores need a model: keep the original ones. Only scores a judge owns, never a pass criterion, so no
        # verdict or credit can come from the old grading.
        judges = [evaluator for evaluator in evaluators if isinstance(evaluator, JudgeEvaluator)]
        produced = {score.name for score in scores}
        scores += [
            _score(old)
            for old in old_scores
            if old["name"] not in produced
            and old["name"] not in scenario.pass_criteria
            and any(judge.owns(old["name"]) for judge in judges)
        ]
    passed = trial_passed(status, scores, scenario.pass_criteria)
    credit, criteria = trial_credit(status, scores, scenario.pass_criteria)
    columns = {
        "scenario_version": scenario.version,
        "passed": passed,
        "credit": credit,
        "criteria_json": json.dumps(criteria),
        "resume_key": _resume_key(row, config, version, scenario.version),
    }
    trial = {**(payload.get("trial") or {}), **columns, "criteria": criteria}
    trial.pop("criteria_json", None)
    extra = {
        **(payload.get("extra") or {}),
        "regraded": {"from_version": version, "passed_before": bool(row["passed"])},
    }
    rewritten = {**payload, "trial": trial, "scores": [score.model_dump() for score in scores], "extra": extra}
    return RegradedTrial(
        trial_id=str(row["trial_id"]), scenario=name, from_version=version, to_version=scenario.version,
        passed_before=bool(row["passed"]), columns=columns, scores=scores, trace=rewritten,
    )  # fmt: skip


def _tasks(scenario: Scenario, cache: dict[str, dict[str, Task]]) -> dict[str, Task]:
    if scenario.name not in cache:
        cache[scenario.name] = {task.id: task for task in scenario.load_tasks()}
    return cache[scenario.name]


def _output(row: dict[str, Any], payload: dict[str, Any], load_artifact: ArtifactLoader) -> TrialOutput | None:
    """The trial's output as the evaluators saw it; None when a file it produced was not kept."""
    extra = payload.get("extra") or {}
    artifacts: dict[str, bytes] = {}
    for span in payload.get("spans", []):
        if span.get("kind") != "step" or span.get("name") != "result":
            continue  # the runner attaches the output's files to the result step (runner/run.py)
        for ref in span.get("artifacts", []):
            loaded = load_artifact(ref["key"]) if ref.get("key") else None
            if loaded is None:
                return None
            artifacts[ref["name"]] = loaded[0]
    return TrialOutput(final=str(row.get("final") or ""), env_state=extra.get("env_state") or {},
                       extras=extra.get("extras") or {}, artifacts=artifacts)  # fmt: skip


def _score(row: dict[str, Any]) -> Score:
    value = row.get("value")
    return Score(name=row["name"], value=float("nan") if value is None else float(value), level=row["level"],
                 passed=row.get("passed"), rationale=row.get("rationale") or "")  # fmt: skip


def _resume_key(row: dict[str, Any], config: dict[str, Any], old: str, new: str) -> str:
    """The key a rerun of this trial under the new version would have, so resuming the run still skips it.

    Only when the stored key is reproduced from the run's seed; otherwise it is left as it was.
    """
    stored = str(row.get("resume_key") or "")
    seed = int(config.get("seed", 0)) + int(row.get("repeat") or 0)
    fingerprint, task_fp = str(row.get("fingerprint") or ""), str(row.get("task_fp") or "")
    if not stored or resume_key(fingerprint, old, task_fp, seed) != stored:
        return stored
    return resume_key(fingerprint, new, task_fp, seed)
