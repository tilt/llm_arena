"""DecisionPolicy: the one interface a workflow uses for control decisions, plus rules and cascades."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from llm_arena.decisions.types import Answer, DecisionRequest, DecisionResult

Rule = Callable[[DecisionRequest], Answer | None]  # None = abstain


class DecisionPolicy(Protocol):
    @property
    def name(self) -> str: ...

    async def decide(self, request: DecisionRequest) -> DecisionResult: ...


class RulePolicy:
    """Deterministic rules per question name; a rule may abstain (return None)."""

    def __init__(self, rules: dict[str, Rule], name: str = "rules") -> None:
        self._rules = rules
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        answers: dict[str, Answer] = {}
        for question_name, question in request.questions.items():
            rule = self._rules.get(question_name)
            answer = rule(request) if rule else None
            answers[question_name] = (
                answer.model_copy(update={"source": self._name})
                if answer
                else Answer(type=question.type, abstained=True, source=self._name)
            )
        return DecisionResult(answers=answers)


class CascadePolicy:
    """Hard rules first; then the primary policy; questions it answers with low confidence go to the fallback.

    This is the "cheap and fast for routine decisions, expensive reasoning only when uncertain" set-up.
    Thresholds are per question (default for the rest); tune them on the dev split and freeze them.
    """

    def __init__(
        self,
        primary: DecisionPolicy,
        fallback: DecisionPolicy | None = None,
        *,
        hard_rules: RulePolicy | None = None,
        threshold: float = 0.8,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.hard_rules = hard_rules
        self.threshold = threshold
        self.thresholds = thresholds or {}

    @property
    def name(self) -> str:
        parts = [f"rules+{self.primary.name}" if self.hard_rules else self.primary.name]
        if self.fallback:
            parts.append(self.fallback.name)
        return "→".join(parts)

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        started = time.perf_counter()
        answers: dict[str, Answer] = {}
        cost, tokens = 0.0, 0
        open_questions = dict(request.questions)
        if self.hard_rules:
            ruled = await self.hard_rules.decide(request)
            answers.update({k: a for k, a in ruled.answers.items() if not a.abstained})
            open_questions = {k: q for k, q in open_questions.items() if k not in answers}
        if open_questions:
            first = await self.primary.decide(request.model_copy(update={"questions": open_questions}))
            answers.update(first.answers)
            cost, tokens = cost + first.cost_usd, tokens + first.tokens
            uncertain = {k: q for k, q in open_questions.items() if _uncertain(first.answers.get(k), self._limit(k))}
            if uncertain and self.fallback:
                second = await self.fallback.decide(request.model_copy(update={"questions": uncertain}))
                answers.update({k: a.model_copy(update={"escalated": True}) for k, a in second.answers.items()})
                cost, tokens = cost + second.cost_usd, tokens + second.tokens
        return DecisionResult(answers=answers, cost_usd=cost, tokens=tokens, latency_s=time.perf_counter() - started)

    def _limit(self, question: str) -> float:
        return self.thresholds.get(question, self.threshold)


def _uncertain(answer: Answer | None, limit: float) -> bool:
    return answer is None or answer.abstained or answer.confidence < limit


def describe(request: DecisionRequest) -> dict[str, Any]:
    """Compact record of a request for traces (questions without long criteria texts)."""
    return {"point": request.point, "questions": {k: q.type for k, q in request.questions.items()}}
