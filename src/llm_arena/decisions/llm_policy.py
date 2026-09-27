"""Control decisions from any chat model via structured output (the usual way agents decide today).

The model states a probability per option. Those are verbalised estimates, not calibrated
probabilities — how well they are calibrated compared with a dedicated decision model is exactly
what the arena measures.
"""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, Field

from llm_arena.decisions.types import (
    Answer,
    Choice,
    DecisionRequest,
    DecisionResult,
    Noul,
    Question,
    choice_answer,
    noul_answer,
    score_answer,
)  # fmt: skip
from llm_arena.llm.client import LLMClient, structured, system, user


class _Estimate(BaseModel):
    question: str
    probabilities: dict[str, float] = Field(description="option -> probability; probabilities sum to 1")


class _Decisions(BaseModel):
    answers: list[_Estimate]


def options(question: Question) -> list[str]:
    if isinstance(question, Noul):
        return ["true", "false"]
    if isinstance(question, Choice):
        return list(question.criteria)
    return [str(level) for level in range(len(question.criteria))]


def render_questions(request: DecisionRequest) -> str:
    lines = []
    for name, question in request.questions.items():
        if isinstance(question, Noul):
            detail = "options: true | false"
            if question.criteria:
                detail += "".join(f"\n    {k}: {v}" for k, v in question.criteria.items())
        elif isinstance(question, Choice):
            detail = "options:" + "".join(f"\n    {k}: {v}" for k, v in question.criteria.items())
        else:
            detail = "options (ordered levels):" + "".join(
                f"\n    {i}: {level}" for i, level in enumerate(question.criteria)
            )
        lines.append(f"- {name} ({question.type}): {question.instructions}\n  {detail}")
    return "\n".join(lines)


class LLMDecisionPolicy:
    def __init__(self, client: LLMClient, label: str | None = None) -> None:
        self._client = client
        self._name = label or f"llm:{client.spec.name}"

    @property
    def name(self) -> str:
        return self._name

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        started = time.perf_counter()
        state = (
            request.state
            if isinstance(request.state, str)
            else json.dumps(request.state, ensure_ascii=False, default=str)
        )
        messages = [
            system(
                "You make control decisions for an automated agent. Answer every question independently from the "
                "state. For each question give a probability for every option; the probabilities must sum to 1 and "
                "express how sure you are."
            ),
            user(f"STATE:\n{state}\n\nQUESTIONS:\n{render_questions(request)}"),
        ]
        parsed, responses = await structured(self._client, messages, _Decisions, temperature=0.0)
        by_name = {estimate.question: estimate.probabilities for estimate in parsed.answers}
        answers = {
            name: _to_answer(question, by_name.get(name, {}), self._name)
            for name, question in request.questions.items()
        }
        return DecisionResult(
            answers=answers,
            cost_usd=sum(r.usage.cost_usd for r in responses),
            tokens=sum(r.usage.total_tokens for r in responses),
            latency_s=time.perf_counter() - started,
        )


def _to_answer(question: Question, raw: dict[str, float], source: str) -> Answer:
    allowed = options(question)
    probabilities = {option: float(raw.get(option, 0.0)) for option in allowed}  # invented options are dropped
    if not any(probabilities.values()):
        probabilities = dict.fromkeys(allowed, 1 / len(allowed))  # no usable answer: maximally uncertain
    if isinstance(question, Noul):
        total = probabilities["true"] + probabilities["false"]
        return noul_answer(probabilities["true"] / total, source)
    if isinstance(question, Choice):
        return choice_answer(probabilities, source)
    return score_answer(probabilities, source)
