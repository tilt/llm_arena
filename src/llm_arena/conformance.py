"""Conformance vectors: scripted runs whose requests and scores any engine implementation must reproduce.

Each case plays fixed model replies per role through a scenario and records (a) every message list
each role received — which also exports the scenario prompts as data — and (b) all scores. The
Python engine regenerates them in CI; a Pyodide build or a TypeScript port is checked against the
same files, so "same behaviour" is a test, not a promise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from llm_arena.core.trace import Trace
from llm_arena.decisions.config import DecisionConfig, DecisionSetup
from llm_arena.eval.base import EvalContext
from llm_arena.llm.testing import ScriptedLLM, tool_call
from llm_arena.llm.types import LLMResponse
from llm_arena.patterns.roles import RoleModels
from llm_arena.sandbox.base import Sandbox
from llm_arena.scenarios.base import RunContext, get_scenario

Reply = str | dict[str, Any]  # text, or {"tool": name, "args": {...}} for a native tool call


@dataclass(frozen=True)
class Case:
    id: str
    scenario: str
    task_id: str
    replies: dict[str, list[Reply]]
    params: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, Any] | None = None  # DecisionConfig; its LLM policy plays the "decider" replies


GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
WRONG_SQL = "```sql\nSELECT COUNT(*) FROM rentals WHERE started_at LIKE '2026-03%'\n```"


def _decide(**answers: dict[str, float]) -> str:
    return json.dumps({"answers": [{"question": q, "probabilities": p} for q, p in answers.items()]})


def _step(action: str, done: float = 0.1) -> str:
    return _decide(next_action={action: 0.9, "get_order" if action == "finish" else "finish": 0.1},
                   task_complete={"true": done, "false": 1 - done})  # fmt: skip


APPROVE_NOT_NEEDED = _decide(needs_approval={"true": 0.2, "false": 0.8})
ACCEPT = '{"verdict": "accept", "issues": []}'
REVISE = '{"verdict": "revise", "issues": ["filter by city"]}'

CASES: list[Case] = [
    Case("reflection_sql-fixed-by-critic", "reflection_sql", "harborview_march_rentals",
         {"generator": [WRONG_SQL, GOOD_SQL], "critic": [REVISE]}),
    Case("reflection_sql-regression", "reflection_sql", "harborview_march_rentals",
         {"generator": [GOOD_SQL, WRONG_SQL], "critic": [REVISE]}, {"feedback": "sql_only"}),
    Case("email-forward-invoice", "email_assistant", "forward_invoice",
         {"agent": [{"tool": "search_emails", "args": {"query": "invoice"}},
                    {"tool": "forward_email", "args": {"email_id": 7, "to": ["accounts@quillon.test"]}}, "Forwarded."]}),
    Case("email-collateral-damage", "email_assistant", "delete_without_permission",
         {"agent": [{"tool": "delete_email", "args": {"email_id": 9}}, {"tool": "archive_email", "args": {"email_id": 9}},
                    "Archived instead."]}),
    Case("react-diligent", "react_multihop", "founder_country_selmworks",
         {"agent": ['Thought: founder\nAction: read_article\nAction Input: {"title": "Selmworks"}',
                    'Thought: birthplace\nAction: read_article\nAction Input: {"title": "Benedikt Salo"}',
                    'Thought: country\nAction: read_article\nAction Input: {"title": "Durnhollow"}',
                    "Thought: done\nFinal Answer: Calvoria"]}),
    Case("react-guess", "react_multihop", "founder_country_selmworks", {"agent": ["Final Answer: Westmarch"]}),
    Case("research-selm", "research_report", "selm_tidal",
         {"researcher": [{"tool": "search", "args": {"query": "Selm tidal pilot"}},
                         {"tool": "fetch_document", "args": {"doc_id": "selm_tidal-1"}},
                         "Notes: 12 MW, 2024, Ostreva Energy Cooperative, 38 percent [selm_tidal-1]"],
          "writer": ["The Selm pilot (12 MW) was commissioned in 2024 by the Ostreva Energy Cooperative and reached a "
                     "38 percent capacity factor [selm_tidal-1]."],
          "reviewer": [ACCEPT]}),
    Case("trip-recovers-from-sold-out", "trip_planner", "varrel_morning",
         {"planner": [{"tool": "search_flights", "args": {"origin": "Pellmoor", "destination": "Varrel", "date": "2026-06-20"}},
                      {"tool": "book_flight", "args": {"flight_id": "NR410"}},
                      {"tool": "book_flight", "args": {"flight_id": "NR414"}}, "Booked NR414."]},
         {"mode": "single_loop"}),
    Case("launch-single-agent", "launch_brief", "summer_launch",
         {"orchestrator": [{"tool": "list_products", "args": {}},
                           "## Recommended product\nRidgeline UL1 tent (FS-TENT-UL1)\nTagline: Under a kilo, over the ridge."]},
         {"mode": "single_agent"}),
    Case("writing-fixed", "reflection_writing", "release_notes",
         {"writer": ["Version 3.2 is great.", "- Offline mode for notes and attachments\n- Search is 3x faster\n"
                     "- New dark theme Dusk\n- Fixed: sync conflicts no longer duplicate notes"],
          "critic": ['{"verdict": "revise", "issues": ["use bullets", "mention all features"]}']}),
    Case("shop-policy-violation", "shop_codeact", "refund_outside_window",
         {"agent": ["```python\nfrom api import *\nissue_refund(1003, 58.0, 'request')\n"
                    "send_message('rui.tanaka@mail.test', 'Refunded.')\n```", "FINAL ANSWER: refunded"]}),
    Case("support-desk-policy-control", "support_desk", "damaged_2001",
         {"agent": [{"tool": "get_order", "args": {"order_id": 2001}},
                    {"tool": "issue_refund", "args": {"order_id": 2001, "amount": 24.0, "reason": "cracked bowl"}},
                    {"tool": "send_message", "args": {"customer_email": "ines.moreau@mail.test", "text": "Refunded $24."}},
                    "Refunded $24 and told the customer."],
          "decider": [_step("get_order"), _step("issue_refund"), APPROVE_NOT_NEEDED, _step("send_message"),
                      APPROVE_NOT_NEEDED, _step("finish", 0.9),
                      _decide(task_accomplished={"true": 0.9, "false": 0.1}, needs_human_review={"true": 0.1, "false": 0.9})]},
         decisions={"policy": "llm", "control": "policy"}),
    Case("support-desk-rules-gate", "support_desk", "goodwill_2008",
         {"agent": [{"tool": "issue_refund", "args": {"order_id": 2008, "amount": 15.0, "reason": "goodwill"}},
                    {"tool": "send_message", "args": {"customer_email": "sofia.rossi@mail.test", "text": "No discount, sorry."}},
                    "Explained that no discount is possible."]},
         decisions={"policy": "rules", "control": "gate"}),
]  # fmt: skip


def _script(replies: list[Reply]) -> list[str | LLMResponse]:
    return [tool_call(r["tool"], **r["args"]) if isinstance(r, dict) else r for r in replies]


async def record(case: Case, sandbox: Sandbox | None = None) -> dict[str, Any]:
    """Run one case and return its vector (requests per role, final output, scores)."""
    scenario = get_scenario(case.scenario)
    task = next(t for t in scenario.load_tasks() if t.id == case.task_id)
    clients = {role: ScriptedLLM(_script(replies), name=role) for role, replies in case.replies.items()}
    trace = Trace()
    setup = None
    if case.decisions is not None:
        setup = DecisionSetup(DecisionConfig.model_validate(case.decisions), trace, decider=clients.get("decider"))
    ctx = RunContext(trace=trace, params=scenario.params(case.params), sandbox=sandbox, decisions=setup)
    output = await scenario.run(task, RoleModels(dict(clients), trace), ctx)
    evaluation = EvalContext(task, output, trace, params=ctx.params, sandbox=sandbox)
    scores = {s.name: {"value": round(s.value, 6), "passed": s.passed} for e in scenario.evaluators(ctx.params)
              for s in await e.evaluate(evaluation)}  # fmt: skip
    vector: dict[str, Any] = json.loads(
        json.dumps(
            {
                "case": {
                    "id": case.id,
                    "scenario": case.scenario,
                    "task_id": case.task_id,
                    "params": case.params,
                    "replies": case.replies,
                    "decisions": case.decisions,
                },  # fmt: skip
                "requests": {role: client.calls for role, client in clients.items()},
                "final": output.final,
                "scores": scores,
                "decisions": [
                    {
                        "point": span.name,
                        "labels": span.attrs.get("labels"),
                        "human": span.attrs.get("human"),
                        "predictions": {
                            q: {
                                "choice": a.get("choice"),
                                "p_true": a["probabilities"].get("true"),
                                "abstained": a.get("abstained"),
                            }
                            for q, a in (span.output or {}).items()
                        },
                    }
                    for span in trace.select("decision")
                ],  # fmt: skip
            },
            default=str,
        )
    )
    return vector


def needs_sandbox(case: Case) -> bool:
    return "sandbox" in get_scenario(case.scenario).requires
