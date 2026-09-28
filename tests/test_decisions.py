import json
from typing import Any

import pytest

from llm_arena.core.trace import Trace
from llm_arena.decisions import CascadePolicy, Choice, DecisionRequest, LLMDecisionPolicy, Noul, RulePolicy, Score
from llm_arena.decisions.jev import JevDecisionPolicy
from llm_arena.decisions.tracing import TracedPolicy
from llm_arena.decisions.types import Answer, noul_answer
from llm_arena.llm.errors import ProviderError
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.llm.transport import HttpResponse
from llm_arena.runner.budget import BudgetExceededError, BudgetGuard

REQUEST = DecisionRequest(
    point="step",
    state={"order": 7, "action": "issue_refund"},
    questions={
        "next_action": Choice(instructions="What next?", criteria={"get_order": "look up", "finish": "stop"}),
        "needs_approval": Noul(instructions="Does this need a human?"),
        "risk": Score(instructions="How risky?", criteria=["low", "medium", "high"]),
    },
)


def llm_reply(**answers: dict[str, float]) -> str:
    return json.dumps(answers)


async def test_llm_policy_maps_probabilities() -> None:
    llm = ScriptedLLM([llm_reply(next_action={"get_order": 0.7, "finish": 0.2, "invented": 0.1},
                                 needs_approval={"true": 0.9, "false": 0.1}, risk={"0": 0.1, "1": 0.3, "2": 0.6})])  # fmt: skip
    result = await LLMDecisionPolicy(llm).decide(REQUEST)
    choice = result.answers["next_action"]
    assert choice.choice == "get_order" and set(choice.probabilities) == {"get_order", "finish"}
    assert choice.confidence == pytest.approx(0.7 / 0.9)
    assert result.answers["needs_approval"].yes and result.answers["needs_approval"].p_true == pytest.approx(0.9)
    assert result.answers["risk"].score == pytest.approx(1.5)
    assert result.tokens > 0 and result.answers["risk"].source == "llm:scripted"


async def test_llm_policy_without_a_valid_answer_abstains() -> None:
    result = await LLMDecisionPolicy(ScriptedLLM([llm_reply()])).decide(REQUEST)  # missing questions fail the schema
    assert all(answer.abstained for answer in result.answers.values())


async def test_llm_policy_schema_uses_question_and_option_names() -> None:
    from llm_arena.decisions.llm_policy import response_model

    schema = response_model(REQUEST).model_json_schema()
    assert schema["required"] == ["next_action", "needs_approval", "risk"]
    risk = schema["$defs"]["Q2"]
    assert risk["required"] == ["0", "1", "2"]


def approval_rule(request: DecisionRequest) -> Answer | None:
    return noul_answer(1.0, "rules") if request.state.get("action") == "issue_refund" else None  # type: ignore[union-attr]


async def test_rules_abstain_without_a_rule() -> None:
    result = await RulePolicy({"needs_approval": approval_rule}).decide(REQUEST)
    assert result.answers["needs_approval"].yes and not result.answers["needs_approval"].abstained
    assert result.answers["next_action"].abstained


async def test_cascade_escalates_only_uncertain_answers() -> None:
    primary = LLMDecisionPolicy(ScriptedLLM([llm_reply(next_action={"get_order": 0.95, "finish": 0.05},
                                                       needs_approval={"true": 0.55, "false": 0.45},
                                                       risk={"0": 0.9, "1": 0.1, "2": 0.0})], name="small"))  # fmt: skip
    fallback = LLMDecisionPolicy(ScriptedLLM([llm_reply(needs_approval={"true": 0.99, "false": 0.01})], name="big"))
    cascade = CascadePolicy(primary, fallback, threshold=0.8)
    result = await cascade.decide(REQUEST)
    assert result.answers["needs_approval"].escalated and result.answers["needs_approval"].p_true == pytest.approx(0.99)
    assert not result.answers["next_action"].escalated and result.answers["next_action"].choice == "get_order"
    assert "small" in cascade.name and "big" in cascade.name


async def test_cascade_hard_rules_win() -> None:
    never = LLMDecisionPolicy(ScriptedLLM([llm_reply(needs_approval={"true": 0.0, "false": 1.0})]))
    result = await CascadePolicy(never, hard_rules=RulePolicy({"needs_approval": approval_rule})).decide(REQUEST)
    assert result.answers["needs_approval"].yes and result.answers["needs_approval"].source == "rules"


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    async def post_json(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
    ) -> HttpResponse:
        self.requests.append({"url": url, "headers": headers, "body": body})
        return self.responses.pop(0)


JEV_OK = HttpResponse(200, {
    "model": "jev-latest",
    "answers": {
        "next_action": {"type": "choice", "choice": "finish", "probabilities": {"finish": 0.8, "get_order": 0.2}, "confidence": 0.8},
        "needs_approval": {"type": "noul", "noul": 0.97},
        "risk": {"type": "score", "score": 2, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.8}, "confidence": 0.8},
    },
    "usage": {"input_tokens": 1000, "output_tokens": 12},
})  # fmt: skip


async def test_jev_request_and_answers() -> None:
    transport = FakeTransport([HttpResponse(429, {"error": "slow down"}), JEV_OK])
    result = await JevDecisionPolicy(transport, "k", backoff_s=0).decide(REQUEST)
    sent = transport.requests[-1]
    assert sent["url"].endswith("/v1/systemone") and sent["headers"]["Authorization"] == "Bearer k"
    assert sent["body"]["questions"]["risk"] == {
        "type": "score",
        "instructions": "How risky?",
        "criteria": ["low", "medium", "high"],
    }
    assert "criteria" not in sent["body"]["questions"]["needs_approval"]
    assert result.answers["next_action"].choice == "finish"
    assert result.answers["needs_approval"].confidence == pytest.approx(0.97)
    assert result.cost_usd == pytest.approx(1000 * 0.042e-6) and result.tokens == 1000


async def test_jev_permanent_error_is_not_retried() -> None:
    transport = FakeTransport([HttpResponse(401, {"error": "bad key"}), JEV_OK])
    with pytest.raises(ProviderError, match="401"):
        await JevDecisionPolicy(transport, "k", backoff_s=0).decide(REQUEST)
    assert len(transport.requests) == 1


async def test_traced_policy_records_span_and_charges_budget() -> None:
    trace, budget = Trace(), BudgetGuard(1.0)
    policy = TracedPolicy(LLMDecisionPolicy(ScriptedLLM([llm_reply()])), trace, budget)
    await policy.decide(REQUEST, labels={"needs_approval": True})
    (span,) = trace.select("decision")
    assert span.attrs["labels"] == {"needs_approval": True} and set(span.output) == set(REQUEST.questions)
    assert budget.spent_usd == pytest.approx(span.cost_usd)
    budget.charge(5)
    with pytest.raises(BudgetExceededError):
        await policy.decide(REQUEST)


async def test_jev_spend_is_charged_and_counted_in_trace_totals() -> None:
    trace, budget = Trace(), BudgetGuard(1.0)
    policy = TracedPolicy(JevDecisionPolicy(FakeTransport([JEV_OK]), "k"), trace, budget)
    await policy.decide(REQUEST)
    assert budget.spent_usd == pytest.approx(1000 * 0.042e-6)
    assert trace.totals()["cost_usd"] == pytest.approx(budget.spent_usd)
