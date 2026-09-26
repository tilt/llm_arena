"""Turn a run's rows into report-ready summaries (pure computation, no storage, no rendering)."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from llm_arena.eval.metrics import (
    bootstrap_ci,
    bradley_terry,
    mean,
    paired_permutation_test,
    pass_at_k,
    pass_hat_k,
    percentile,
)
from llm_arena.runner.ports import RunData


@dataclass
class ConfigSummary:
    scenario: str
    pattern: str
    config: str
    roles: dict[str, str]
    trials: int
    tasks: int
    repeats: int
    pass_rate: float
    ci_low: float
    ci_high: float
    pass_hat_k: float  # all k repeats pass (reliability)
    pass_at_k: float  # at least one of k passes (capability)
    errors: int
    mean_tokens: float
    mean_cost_usd: float
    judge_cost_usd: float
    latency_p50_s: float
    latency_p95_s: float
    step_means: dict[str, float] = field(default_factory=dict)
    e2e_means: dict[str, float] = field(default_factory=dict)
    derived: dict[str, float] = field(default_factory=dict)  # reviewer precision/recall …
    per_task_pass: dict[str, float] = field(default_factory=dict)


@dataclass
class PairedTest:
    scenario: str
    best: str
    other: str
    difference: float
    p_value: float
    tasks: int


@dataclass
class RunSummary:
    run_id: str
    name: str
    created_at: str
    config_json: dict[str, Any]
    configs: list[ConfigSummary]
    paired_tests: list[PairedTest]
    ratings: dict[str, dict[str, float]]  # scenario ("overall" too) -> config -> rating
    battles: int
    trials: list[dict[str, Any]]
    scores: dict[str, list[dict[str, Any]]]  # trial_id -> scores

    @property
    def scenarios(self) -> list[str]:
        return sorted({c.scenario for c in self.configs})

    @property
    def config_names(self) -> list[str]:
        return sorted({c.config for c in self.configs})


def summarize(data: RunData) -> RunSummary:
    """Pure: the same summary whichever store produced the rows (DuckDB, memory, browser)."""
    scores: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data.scores:
        scores[row["trial_id"]].append(row)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trial in data.trials:
        groups[(trial["scenario"], trial["config"])].append(trial)
    configs = [_summarize_group(key, members, scores) for key, members in sorted(groups.items())]
    return RunSummary(
        run_id=data.run.get("run_id", ""),
        name=data.run.get("name", ""),
        created_at=str(data.run.get("created_at", ""))[:19],
        config_json=json.loads(data.run.get("config_json") or "{}"),
        configs=configs,
        paired_tests=_paired_tests(configs),
        ratings=_ratings(data.battles),
        battles=len(data.battles),
        trials=data.trials,
        scores=dict(scores),
    )


def _summarize_group(
    key: tuple[str, str], trials: list[dict[str, Any]], scores: dict[str, list[dict[str, Any]]]
) -> ConfigSummary:
    scenario, config = key
    by_task: dict[str, list[bool]] = defaultdict(list)
    for trial in trials:
        by_task[trial["task_id"]].append(bool(trial["passed"]))
    k = min(len(v) for v in by_task.values())
    passed = [float(trial["passed"]) for trial in trials]
    rate, low, high = bootstrap_ci(passed)
    metric_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for trial in trials:
        for score in scores.get(trial["trial_id"], []):
            if score["value"] is not None and not math.isnan(score["value"]):
                metric_values[(score["level"], score["name"])].append(score["value"])
    step = {name: mean(values) for (level, name), values in sorted(metric_values.items()) if level == "step"}
    e2e = {name: mean(values) for (level, name), values in sorted(metric_values.items()) if level == "e2e"}
    durations = [trial["duration_s"] for trial in trials]
    return ConfigSummary(
        scenario=scenario,
        pattern=trials[0]["pattern"],
        config=config,
        roles=json.loads(trials[0]["roles_json"] or "{}"),
        trials=len(trials),
        tasks=len(by_task),
        repeats=k,
        pass_rate=rate,
        ci_low=low,
        ci_high=high,
        pass_hat_k=mean([pass_hat_k(len(v), sum(v), k) for v in by_task.values()]),
        pass_at_k=mean([pass_at_k(len(v), sum(v), k) for v in by_task.values()]),
        errors=sum(trial["status"] != "ok" for trial in trials),
        mean_tokens=mean([trial["prompt_tokens"] + trial["completion_tokens"] for trial in trials]),
        mean_cost_usd=mean([trial["cost_usd"] for trial in trials]),
        judge_cost_usd=sum(trial["judge_cost_usd"] or 0.0 for trial in trials),
        latency_p50_s=percentile(durations, 0.5),
        latency_p95_s=percentile(durations, 0.95),
        step_means=step,
        e2e_means=e2e,
        derived=_derived(step),
        per_task_pass={task: mean([float(p) for p in v]) for task, v in by_task.items()},
    )


def _derived(step: dict[str, float]) -> dict[str, float]:
    """Reviewer precision/recall from the critic_tp/fp/fn indicator means (same denominator)."""
    if not {"critic_tp", "critic_fp", "critic_fn"} <= set(step):
        return {}
    tp, fp, fn = step["critic_tp"], step["critic_fp"], step["critic_fn"]
    return {
        "reviewer_precision": tp / (tp + fp) if tp + fp else float("nan"),
        "reviewer_recall": tp / (tp + fn) if tp + fn else float("nan"),
    }


def _paired_tests(configs: list[ConfigSummary]) -> list[PairedTest]:
    tests = []
    by_scenario: dict[str, list[ConfigSummary]] = defaultdict(list)
    for config in configs:
        by_scenario[config.scenario].append(config)
    for scenario, members in sorted(by_scenario.items()):
        if len(members) < 2:
            continue
        best = max(members, key=lambda c: c.pass_rate)
        for other in members:
            if other is best:
                continue
            shared = sorted(set(best.per_task_pass) & set(other.per_task_pass))
            a = [best.per_task_pass[t] for t in shared]
            b = [other.per_task_pass[t] for t in shared]
            tests.append(
                PairedTest(
                    scenario, best.config, other.config, mean(a) - mean(b), paired_permutation_test(a, b), len(shared)
                )
            )
    return tests


def _ratings(battles: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    if not battles:
        return {}
    by_scenario: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for battle in battles:
        by_scenario[battle["scenario"]].append((battle["config_a"], battle["config_b"], battle["winner"]))
    ratings = {scenario: bradley_terry(matches) for scenario, matches in by_scenario.items()}
    ratings["overall"] = bradley_terry([match for matches in by_scenario.values() for match in matches])
    return ratings
