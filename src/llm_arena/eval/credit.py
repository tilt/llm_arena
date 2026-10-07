"""Partial credit: how much of a task's graded work a trial got done, next to the strict pass verdict.

A pass criterion's `Score.value` is its credit in [0, 1] and `passed` its verdict, so a trial that did three of four
things no longer looks like one that did nothing. Credit never replaces the pass rate; it explains it and breaks
ranking ties.

- A criterion that passed earns 1; one that failed earns its value when that is a share below 1, else 0, so credit
  is 1 exactly when the trial passed.
- A trial's credit is the mean over the criteria that decided its verdict; errors and timeouts earn 0.
- State checks use `change_credit`: only expectations the initial state did not meet count as work, and expectations
  the agent broke count against it, so doing nothing earns 0 and collateral damage costs credit.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from llm_arena.eval.base import Score

__all__ = ["change_credit", "criterion_credit", "share", "trial_credit", "trial_passed", "with_credit"]


def criterion_credit(passed: bool, value: float | None) -> float:
    """1 for a passed criterion. A failed one earns its value only when that is a share in [0, 1): a value of 1 or
    more (or a negative one) contradicts the verdict and is no share of anything, so it earns nothing rather than
    letting a failure look complete."""
    if passed:
        return 1.0
    if value is None or math.isnan(value) or not 0.0 <= value < 1.0:
        return 0.0
    return float(value)


def trial_passed(status: str, scores: Iterable[Score], criteria: Iterable[str]) -> bool:
    """The verdict: the trial ran, and every pass criterion that produced a verdict passed (at least one did)."""
    wanted = set(criteria)
    graded = [score for score in scores if score.name in wanted and score.passed is not None]
    return status == "ok" and bool(graded) and all(score.passed for score in graded)


def trial_credit(
    status: str, scores: Iterable[Score], criteria: Iterable[str]
) -> tuple[float, dict[str, dict[str, Any]]]:
    """(credit, {criterion: {"credit", "passed"}}) over the graded criteria, in `criteria` order."""
    if status != "ok":
        return 0.0, {}
    by_name = {score.name: score for score in scores if score.passed is not None}
    graded = {
        name: {"credit": criterion_credit(bool(by_name[name].passed), by_name[name].value),
               "passed": bool(by_name[name].passed)}
        for name in criteria if name in by_name
    }  # fmt: skip
    if not graded:
        return 0.0, {}
    return sum(c["credit"] for c in graded.values()) / len(graded), graded


def change_credit(before: Mapping[str, bool], after: Mapping[str, bool]) -> float:
    """Share of the needed work done: checks failing before that hold after, over needed + broken checks.

    `before` and `after` are the same keyed checks run on the initial and the final state. A key missing from
    `before` counts as already met.
    """
    needed = [key for key in after if not before.get(key, True)]
    broken = [key for key in after if before.get(key, True) and not after[key]]
    if not needed and not broken:
        return 1.0
    return sum(after[key] for key in needed) / (len(needed) + len(broken))


def share(checks: Mapping[str, bool]) -> float:
    """Share of keyed checks that hold (1.0 when there is nothing to check)."""
    return sum(checks.values()) / len(checks) if checks else 1.0


def with_credit(
    trials: list[dict[str, Any]], scores: list[dict[str, Any]], criteria_of: Callable[[str], list[str] | None]
) -> list[dict[str, Any]]:
    """Fill in `credit`/`criteria_json` for trial rows stored before credit existed, from their score rows.

    Only the stored score values are used, as they were graded then: sub-checks added since cannot be recovered, so
    an old binary criterion stays 0 or 1. `criteria_of(scenario)` returns the scenario's current pass criteria, or
    None when it is unknown (left without credit).
    """
    if all(row.get("criteria_json") for row in trials):
        return trials
    by_trial: dict[str, list[Score]] = {}
    for row in scores:
        if row.get("passed") is None:
            continue
        by_trial.setdefault(str(row["trial_id"]), []).append(
            Score(name=row["name"], value=float(row["value"] if row["value"] is not None else math.nan),
                  level=row["level"], passed=bool(row["passed"]))
        )  # fmt: skip
    filled = []
    for row in trials:
        criteria = None if row.get("criteria_json") else criteria_of(str(row["scenario"]))
        if criteria is None:
            filled.append(row)
            continue
        credit, detail = trial_credit(str(row.get("status", "ok")), by_trial.get(str(row["trial_id"]), []), criteria)
        if (credit >= 1.0) != bool(row.get("passed")):
            # `criteria_of` gives today's pass criteria; if the version that graded this trial used others, the
            # rebuilt credit contradicts its stored verdict. Leave it unknown rather than show a wrong number.
            filled.append(row)
            continue
        filled.append({**row, "credit": credit, "criteria_json": json.dumps(detail)})
    return filled
