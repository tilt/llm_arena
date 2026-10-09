"""Control decisions from any chat model via structured output (the usual way agents decide today).

The response schema is generated from the questions: one field per question, one probability per
option. Constrained decoding then cannot invent question or option names. The probabilities are
verbalised estimates, not calibrated ones; how well they are calibrated compared with a dedicated
decision model is exactly what the arena measures.
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

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
from llm_arena.llm.errors import StructuredOutputError

# Caps a runaway generation (a thinking model looping); decisions are short. Thinking models need headroom.
DECISION_MAX_TOKENS = 4096


def options(question: Question) -> list[str]:
    if isinstance(question, Noul):
        return ["true", "false"]
    if isinstance(question, Choice):
        return list(question.criteria)
    return [str(level) for level in range(len(question.criteria))]


def response_model(request: DecisionRequest) -> type[BaseModel]:
    """{question: {option: probability}} with every question and option required, as a pydantic model."""
    config = ConfigDict(populate_by_name=True)
    fields: dict[str, Any] = {}
    for index, (name, question) in enumerate(request.questions.items()):
        probabilities: dict[str, Any] = {
            f"o{j}": (float, Field(ge=0.0, le=1.0, alias=option)) for j, option in enumerate(options(question))
        }
        inner = create_model(f"Q{index}", __config__=config, **probabilities)
        fields[f"q{index}"] = (inner, Field(alias=name, description=f"probability of each option for {name}"))
    return create_model("Decisions", __config__=config, **fields)


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
    reserve_usd = 0.0  # its calls reserve through the budgeted client

    def __init__(self, client: LLMClient, label: str | None = None, *, max_tokens: int = DECISION_MAX_TOKENS) -> None:
        self._client = client
        self._name = label or f"llm:{client.spec.name}"
        self._max_tokens = max_tokens

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
                "state. For each question give a probability for every option; a question's probabilities sum to 1 "
                "and express how sure you are."
            ),
            user(f"STATE:\n{state}\n\nQUESTIONS:\n{render_questions(request)}"),
        ]
        model = response_model(request)
        try:
            parsed, responses = await structured(
                self._client, messages, model, temperature=0.0, max_tokens=self._max_tokens
            )
        except StructuredOutputError:
            # No usable answer: the policy has no opinion (recorded as abstentions; approvals then go to a human).
            answers = {
                name: Answer(type=q.type, abstained=True, source=self._name) for name, q in request.questions.items()
            }
            return DecisionResult(answers=answers, latency_s=time.perf_counter() - started)
        by_name: dict[str, dict[str, float]] = parsed.model_dump(by_alias=True)
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
    probabilities = {option: float(raw.get(option, 0.0)) for option in allowed}
    if not any(probabilities.values()):
        return Answer(type=question.type, abstained=True, source=source)  # all zero: no opinion, not 50/50
    if isinstance(question, Noul):
        total = probabilities["true"] + probabilities["false"]
        return noul_answer(probabilities["true"] / total, source)
    if isinstance(question, Choice):
        return choice_answer(probabilities, source)
    return score_answer(probabilities, source)
