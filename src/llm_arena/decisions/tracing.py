"""Record every decision in the trace and charge it to the run's budget."""

from __future__ import annotations

from typing import Any

from llm_arena.core.trace import Trace
from llm_arena.decisions.policy import DecisionPolicy
from llm_arena.decisions.types import DecisionRequest, DecisionResult
from llm_arena.runner.budget import BudgetExceededError, BudgetGuard


class TracedPolicy:
    """Wraps a policy: one `decision` span per request, holding answers and ground-truth labels when known."""

    def __init__(self, policy: DecisionPolicy, trace: Trace, budget: BudgetGuard | None = None) -> None:
        self.policy = policy
        self.trace = trace
        self.budget = budget
        self.last_span: int | None = None  # trace index of the latest decision span

    @property
    def name(self) -> str:
        return self.policy.name

    async def decide(self, request: DecisionRequest, labels: dict[str, Any] | None = None) -> DecisionResult:
        if self.budget is not None and self.budget.exceeded:
            raise BudgetExceededError(f"spend limit of ${self.budget.limit_usd:.2f} reached")
        with self.trace.span("decision", request.point, model=self.policy.name, input=request.state) as span:
            self.last_span = len(self.trace.spans) - 1
            first_child = len(self.trace.spans)
            result = await self.policy.decide(request)
            # LLM stages record (and are charged through) their own llm_call spans; what remains is spend on
            # non-LLM services such as Jev, which the trace totals and the budget must see too.
            llm_cost = sum(s.cost_usd for s in self.trace.spans[first_child:] if s.kind == "llm_call")
            external = max(0.0, result.cost_usd - llm_cost)
            if self.budget is not None:
                self.budget.charge(external)
            span.cost_usd = result.cost_usd
            span.attrs["external_cost_usd"] = external
            span.output = {name: answer.model_dump() for name, answer in result.answers.items()}
            span.attrs.update({"labels": labels or {}, "policy": self.policy.name, "latency_s": result.latency_s,
                               "questions": {k: q.type for k, q in request.questions.items()}})  # fmt: skip
        return result

    def annotate(self, **attrs: Any) -> None:
        """Add what happened after the latest decision (e.g. the human approver's verdict) to its span."""
        if self.last_span is not None:
            self.trace.spans[self.last_span].attrs.update(attrs)
