"""Typed control decisions: the questions an agent loop asks, and normalised answers with probabilities.

The shapes follow the three primitives of "System One" decision models (TypeSafe's Jev): a yes/no
probability (noul), a choice among named options, and a score on an ordered rubric. Every policy —
LLM, rules, cascade, Jev — answers in this one format, so they are interchangeable in a workflow.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Noul(BaseModel):
    type: Literal["noul"] = "noul"
    instructions: str
    criteria: dict[str, str] | None = Field(
        default=None, description='optional {"true": ..., "false": ...} clarifications'
    )


class Choice(BaseModel):
    type: Literal["choice"] = "choice"
    instructions: str
    criteria: dict[str, str] = Field(description="option -> description")


class Score(BaseModel):
    type: Literal["score"] = "score"
    instructions: str
    criteria: list[str] = Field(min_length=2, max_length=10, description="ordered levels, lowest first")


Question = Annotated[Noul | Choice | Score, Field(discriminator="type")]


class Answer(BaseModel):
    type: Literal["noul", "choice", "score"]
    # noul: P(true). choice/score: distribution over options / level indices ("0", "1", ...).
    probabilities: dict[str, float] = Field(default_factory=dict)
    choice: str | None = None  # choice: winning option
    score: float | None = None  # score: expected level index
    confidence: float = 0.0  # 0..1; for noul derived as max(p, 1 - p)
    source: str = ""  # which policy produced it, e.g. "rules", "llm:ollama:qwen3:4b", "jev"
    escalated: bool = False  # answered by a cascade's fallback
    abstained: bool = False  # a rule had no opinion

    @property
    def p_true(self) -> float:
        return self.probabilities.get("true", 0.0)

    @property
    def yes(self) -> bool:
        return self.p_true >= 0.5


class DecisionRequest(BaseModel):
    point: str = Field(description="decision point in the workflow, e.g. 'next_action', 'approval', 'review'")
    state: dict[str, Any] | str
    questions: dict[str, Question]


class DecisionResult(BaseModel):
    answers: dict[str, Answer]
    cost_usd: float = 0.0
    latency_s: float = 0.0
    tokens: int = 0


def noul_answer(p_true: float, source: str) -> Answer:
    p = min(1.0, max(0.0, p_true))
    return Answer(type="noul", probabilities={"true": p, "false": 1 - p}, confidence=max(p, 1 - p), source=source)


def choice_answer(probabilities: dict[str, float], source: str) -> Answer:
    total = sum(max(0.0, v) for v in probabilities.values())
    normalised = {k: max(0.0, v) / total for k, v in probabilities.items()} if total > 0 else probabilities
    best = max(normalised, key=lambda k: normalised[k]) if normalised else None
    return Answer(type="choice", probabilities=normalised, choice=best,
                  confidence=normalised.get(best, 0.0) if best else 0.0, source=source)  # fmt: skip


def score_answer(probabilities: dict[str, float], source: str) -> Answer:
    answer = choice_answer(probabilities, source)
    expected = sum(int(level) * p for level, p in answer.probabilities.items())
    return Answer(
        type="score", probabilities=answer.probabilities, score=expected, confidence=answer.confidence, source=source
    )
