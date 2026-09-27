"""Decision spans → flat rows (one per question) → per config × decision point × question quality metrics.

A row compares the policy's answer with the environment's ground truth. Metrics:
- accuracy, Brier score and log loss (probability given to the true answer), calibration bins;
- for yes/no questions: missed positives (for approval and review questions that is the *false-safe* rate) and
  false alarms (unnecessary escalations to a human);
- escalation / abstention rates, decision latency p50/p95 and cost.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

DECISION_COLUMNS = (
    "trial_id", "scenario", "config", "task_id", "repeat", "span", "point", "question", "qtype", "policy", "source",
    "prediction", "label", "p_true", "p_label", "confidence", "correct", "brier", "escalated", "abstained", "human",
    "latency_s", "cost_usd",
)  # fmt: skip
EPS = 1e-6
BINS = 5


def decision_rows(spans: list[dict[str, Any]], trial: dict[str, Any]) -> list[dict[str, Any]]:
    """`spans` as dumped in a trace payload; `trial` the trial row (ids and config are copied into each row)."""
    rows = []
    for index, span in enumerate(spans):
        if span["kind"] != "decision":
            continue
        attrs = span.get("attrs", {})
        labels = attrs.get("labels", {})
        for question, answer in (span.get("output") or {}).items():
            label = labels.get(question)
            probabilities: dict[str, float] = answer.get("probabilities", {})
            kind = answer.get("type")
            prediction = _prediction(answer)
            truth = None if label is None else _option(label)
            p_label = None if truth is None or answer.get("abstained") else probabilities.get(truth, 0.0)
            rows.append({
                "trial_id": trial["trial_id"], "scenario": trial["scenario"], "config": trial["config"],
                "task_id": trial["task_id"], "repeat": trial["repeat"], "span": index, "point": span["name"],
                "question": question, "qtype": kind, "policy": attrs.get("policy", span.get("model")),
                "source": answer.get("source", ""), "prediction": prediction, "label": truth,
                "p_true": probabilities.get("true") if kind == "noul" else None, "p_label": p_label,
                "confidence": answer.get("confidence", 0.0), "correct": None if truth is None or prediction is None else prediction == truth,
                "brier": None if p_label is None or truth is None else _brier(probabilities, truth),
                "escalated": bool(answer.get("escalated")), "abstained": bool(answer.get("abstained")),
                "human": attrs.get("human"), "latency_s": span.get("duration_s", 0.0),
                "cost_usd": span.get("cost_usd", 0.0),
            })  # fmt: skip
    return rows


def _option(label: Any) -> str:
    return ("true" if label else "false") if isinstance(label, bool) else str(label)


def _prediction(answer: dict[str, Any]) -> str | None:
    if answer.get("abstained"):
        return None
    if answer.get("type") == "noul":
        return "true" if answer.get("probabilities", {}).get("true", 0.0) >= 0.5 else "false"
    if answer.get("type") == "score":
        return None if answer.get("score") is None else str(round(answer["score"]))
    return answer.get("choice")


def _brier(probabilities: dict[str, float], truth: str) -> float:
    options = set(probabilities) | {truth}
    return sum((probabilities.get(o, 0.0) - (1.0 if o == truth else 0.0)) ** 2 for o in options)


class CalibrationBin(BaseModel):
    low: float
    high: float
    n: int
    mean_p: float = Field(description="mean predicted P(true)")
    observed: float = Field(description="share of true labels")


class DecisionSummary(BaseModel):
    scenario: str
    config: str
    policy: str
    point: str
    question: str
    qtype: str
    n: int
    labeled: int
    accuracy: float | None
    brier: float | None
    log_loss: float | None
    missed_rate: float | None = Field(description="noul: P(pred false | label true); approval/review: false-safe")
    false_alarm_rate: float | None = Field(
        description="noul: P(pred true | label false); approval: unnecessary escalations"
    )
    escalation_rate: float
    abstain_rate: float
    human_reviews: int
    latency_p50_s: float
    latency_p95_s: float
    cost_usd: float
    calibration: list[CalibrationBin] = Field(default_factory=list)


def summarize_decisions(rows: list[dict[str, Any]]) -> list[DecisionSummary]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["scenario"], row["config"], row["point"], row["question"])].append(row)
    return [_summary(key, group) for key, group in sorted(groups.items())]


def _summary(key: tuple[str, str, str, str], rows: list[dict[str, Any]]) -> DecisionSummary:
    scenario, config, point, question = key
    labeled = [r for r in rows if r["label"] is not None and not r["abstained"]]
    judged = [r for r in labeled if r["correct"] is not None]
    positives = [r for r in labeled if r["label"] == "true"]
    negatives = [r for r in labeled if r["label"] == "false"]
    spans = {(r["trial_id"], r["span"]): r for r in rows}.values()  # latency and cost are per request
    latencies = sorted(r["latency_s"] for r in spans)
    noul = rows[0]["qtype"] == "noul"
    return DecisionSummary(
        scenario=scenario, config=config, policy=rows[0]["policy"], point=point, question=question,
        qtype=rows[0]["qtype"], n=len(rows), labeled=len(labeled),
        accuracy=_mean([float(r["correct"]) for r in judged]),
        brier=_mean([r["brier"] for r in labeled if r["brier"] is not None]),
        log_loss=_mean([-math.log(max(EPS, r["p_label"])) for r in labeled if r["p_label"] is not None]),
        missed_rate=_mean([float(r["prediction"] == "false") for r in positives]) if noul else None,
        false_alarm_rate=_mean([float(r["prediction"] == "true") for r in negatives]) if noul else None,
        escalation_rate=sum(r["escalated"] for r in rows) / len(rows),
        abstain_rate=sum(r["abstained"] for r in rows) / len(rows),
        human_reviews=sum(1 for r in spans if r["human"]),
        latency_p50_s=_quantile(latencies, 0.5), latency_p95_s=_quantile(latencies, 0.95),
        cost_usd=sum(r["cost_usd"] for r in spans),
        calibration=_calibration(labeled) if noul else [],
    )  # fmt: skip


def _calibration(rows: list[dict[str, Any]]) -> list[CalibrationBin]:
    bins: list[CalibrationBin] = []
    for index in range(BINS):
        low, high = index / BINS, (index + 1) / BINS
        inside = [
            r
            for r in rows
            if r["p_true"] is not None and (low <= r["p_true"] < high or (index == BINS - 1 and r["p_true"] == 1.0))
        ]
        if inside:
            bins.append(CalibrationBin(low=low, high=high, n=len(inside), mean_p=sum(r["p_true"] for r in inside) / len(inside),
                                       observed=sum(r["label"] == "true" for r in inside) / len(inside)))  # fmt: skip
    return bins


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    position = q * (len(values) - 1)
    low = math.floor(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)
