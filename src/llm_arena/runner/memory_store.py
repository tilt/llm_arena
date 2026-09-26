"""In-memory RunStore: used by tests and by the browser engine (which persists to IndexedDB via the UI)."""

from __future__ import annotations

import json
from typing import Any

from llm_arena.core.trace import Trace
from llm_arena.eval.base import Score
from llm_arena.runner.ports import RunData, TrialRecord


def trial_row(run_id: str, record: TrialRecord) -> dict[str, Any]:
    """The flat trial row every store exposes (same columns as the DuckDB `trials` table)."""
    totals = record.totals
    return {
        "trial_id": record.trial_id,
        "run_id": run_id,
        "scenario": record.scenario,
        "pattern": record.pattern,
        "config": record.config,
        "task_id": record.task_id,
        "repeat": record.repeat,
        "status": record.status,
        "passed": record.passed,
        "error": record.error,
        "final": record.final,
        "duration_s": record.duration_s,
        "llm_calls": int(totals.get("llm_calls", 0)),
        "tool_calls": int(totals.get("tool_calls", 0)),
        "prompt_tokens": int(totals.get("prompt_tokens", 0)),
        "completion_tokens": int(totals.get("completion_tokens", 0)),
        "cost_usd": totals.get("cost_usd", 0.0),
        "llm_latency_s": totals.get("llm_latency_s", 0.0),
        "judge_cost_usd": record.judge_cost_usd,
        "roles_json": json.dumps(record.roles),
        "params_json": json.dumps(record.params, default=str),
    }


def trace_payload(record: TrialRecord, scores: list[Score], trace: Trace, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "trial": record.__dict__,
        "scores": [score.model_dump() for score in scores],
        "spans": trace.model_dump()["spans"],
        "extra": extra,
    }


class MemoryStore:
    def __init__(self) -> None:
        self.run: dict[str, Any] = {}
        self.trials: dict[str, dict[str, Any]] = {}
        self.scores: dict[str, list[dict[str, Any]]] = {}
        self.battles: list[dict[str, Any]] = []
        self.traces: dict[str, dict[str, Any]] = {}

    def start_run(self, run_id: str, name: str, config_json: str) -> None:
        self.run = self.run or {"run_id": run_id, "name": name, "created_at": "", "config_json": config_json}

    def completed_trials(self) -> set[str]:
        return {trial_id for trial_id, row in self.trials.items() if row["status"] == "ok"}

    def save_trial(
        self, run_id: str, record: TrialRecord, scores: list[Score], trace: Trace, extra: dict[str, Any]
    ) -> None:
        self.trials[record.trial_id] = trial_row(run_id, record)
        self.scores[record.trial_id] = [{"trial_id": record.trial_id, **score.model_dump()} for score in scores]
        self.traces[record.trial_id] = json.loads(json.dumps(trace_payload(record, scores, trace, extra), default=str))

    def finals_for_battles(self, scenario: str) -> list[tuple[str, str, str]]:
        rows = [
            r for r in self.trials.values() if r["scenario"] == scenario and r["repeat"] == 0 and r["status"] == "ok"
        ]
        return sorted((r["task_id"], r["config"], r["final"]) for r in rows)

    def save_battle(self, scenario: str, task_id: str, a: str, b: str, winner: str, rationale: str) -> None:
        self.battles.append(
            {
                "scenario": scenario,
                "task_id": task_id,
                "config_a": a,
                "config_b": b,
                "winner": winner,
                "rationale": rationale,
            }
        )

    def has_battle(self, scenario: str, task_id: str, a: str, b: str) -> bool:
        return any(
            (x["scenario"], x["task_id"], x["config_a"], x["config_b"]) == (scenario, task_id, a, b)
            for x in self.battles
        )

    def load_run(self) -> RunData:
        return RunData(
            run=dict(self.run),
            trials=sorted(self.trials.values(), key=lambda r: (r["scenario"], r["config"], r["task_id"], r["repeat"])),
            scores=[score for scores in self.scores.values() for score in scores],
            battles=list(self.battles),
        )

    def load_trace(self, trial_id: str) -> dict[str, Any] | None:
        return self.traces.get(trial_id)
