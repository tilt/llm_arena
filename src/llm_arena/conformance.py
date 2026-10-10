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
    return json.dumps(answers)


DESK_ACTIONS = [
    "get_order",
    "list_orders",
    "get_product",
    "send_message",
    "restock",
    "issue_refund",
    "cancel_order",
    "finish",
]


def _step(action: str, done: float = 0.1) -> str:
    return _decide(next_action={a: 0.93 if a == action else 0.01 for a in DESK_ACTIONS},
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
                # Which workflow step each model call, tool call, execution and decision belongs to.
                "steps": [
                    [span.kind, span.name, span.step]
                    for span in trace.spans
                    if span.kind in ("llm_call", "tool_call", "code_exec", "decision")
                ],  # fmt: skip
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


# ---- claim vectors: the same claim and thread must give the same verdicts, statistics and hashes everywhere ---------
def _claim_fixture(**overrides: Any) -> dict[str, Any]:
    """A deterministic claim on reflection_sql (two tasks), as `claims.claim_from_run` would build it."""
    from llm_arena.claims import ClaimSetup, ClaimTask, setup_fingerprint, task_fps_hash  # noqa: PLC0415 (no cycle)
    from llm_arena.runner.fingerprint import task_fingerprint  # noqa: PLC0415

    scenario = get_scenario("reflection_sql")
    tasks = [ClaimTask(id=t.id, fp=task_fingerprint(t)) for t in scenario.load_tasks()[1:3]]
    roles = overrides.pop("roles", None) or {
        "critic": {"provider": "openai", "model": "gpt-4.1-nano", "max_tokens": 512},
        "generator": {"provider": "openai", "model": "gpt-4.1-mini", "max_tokens": 1024},
    }
    setup = ClaimSetup.model_validate({"roles": roles, "params": scenario.params(), "decisions": None})
    claim = {
        "arena_claim": 1, "scenario": scenario.name, "scenario_version": scenario.version,
        "tasks": [t.model_dump() for t in tasks], "task_fps_hash": task_fps_hash(tasks), "seed": 0, "repeats": 1,
        "setup": setup.model_dump(mode="json"), "setup_fp": setup_fingerprint(setup), "judge": None,
        "result": {"passed": 2, "trials": 2, "pass_rate": 1.0, "partial": 1.0, "cost_usd_per_task": 0.0012,
                   "unpriced_roles": [], "engine": "local"},
        "made_at": "2026-10-10T10:00:00+00:00", "arena_version": "0.1.0", "parent_claim_hash": None,
    }  # fmt: skip
    return {**claim, **overrides}


def _repro_body(claim: dict[str, Any], chash: str, passed: list[int], **overrides: Any) -> str:
    from llm_arena.claims import Repro, repro_comment  # noqa: PLC0415

    side = {"setup_fp": claim["setup_fp"], "passed": sum(passed), "trials": len(passed), "errors": 0, "timeouts": 0,
            "budget_stopped": 0, "cost_usd_per_task": 0.0013}  # fmt: skip
    repro = {"arena_repro": 1, "claim_hash": chash, "scenario_version": claim["scenario_version"],
             "task_fps_hash": claim["task_fps_hash"], "judge": None, "baseline": side, "variant": None,
             "per_task": [{"b": b, "v": None} for b in passed], "seen": [], "engine": "pages", "arena_version": "0.1.0",
             **overrides}  # fmt: skip
    return repro_comment(Repro.model_validate(repro))


def _comment(cid: int, user: str, body: str, *, edited: bool = False) -> dict[str, Any]:
    created = f"2026-10-10T10:{cid:02d}:00Z"
    return {"id": cid, "user": {"login": user}, "created_at": created,
            "updated_at": "2026-10-11T00:00:00Z" if edited else created, "body": body}  # fmt: skip


def claim_vector_inputs() -> dict[str, dict[str, Any]]:
    from llm_arena.claims import canonical, check_claim  # noqa: PLC0415

    claim = _claim_fixture()
    text = canonical(claim)
    chash = check_claim(text).claim_hash

    def body(passed: list[int], **overrides: Any) -> str:
        return _repro_body(claim, chash, passed, **overrides)

    judge = {"provider": "openai", "model": "gpt-4.1-mini", "backend": "auto", "tool_mode": "native",
             "temperature": 0.2, "reasoning_effort": None, "max_tokens": 512}  # fmt: skip
    mixed = [
        _comment(1, "alice", body([1, 1])),  # the author
        _comment(2, "bob", body([0, 1])),
        _comment(3, "bob", body([1, 1])),  # supersedes bob's first
        _comment(4, "carol", body([1, 0])),
        _comment(5, "dave", body([1, 1]), edited=True),
        _comment(6, "erin", body([1, 1], claim_hash="e" * 64)),
        _comment(7, "frank", "nice!"),
        _comment(8, "gina", body([1, 1], judge=judge)),
    ]
    three = [_comment(10 + i, f"user{i}", body(p)) for i, p in enumerate([[1, 1], [1, 0], [0, 1]])]
    self_hosted = _claim_fixture(roles={
        "critic": {"provider": "self_hosted", "model": "qwen3-14b"},
        "generator": {"provider": "self_hosted", "model": "qwen3-14b", "max_tokens": 512},
    })  # fmt: skip
    from llm_arena.claims import ClaimSetup, setup_fingerprint  # noqa: PLC0415

    self_hosted["setup_fp"] = setup_fingerprint(ClaimSetup.model_validate(self_hosted["setup"]))
    return {
        "claim-mixed-thread": {"claim": text, "comments": mixed, "author": "alice"},
        "claim-above-interval": {"claim": text, "comments": three, "author": "alice"},
        "claim-partial-thread": {"claim": text, "comments": three, "author": "alice", "total": 400},
        "claim-removed-referenced": {"claim": text, "author": "alice", "comments": [
            _comment(30, "bob", body([1, 1], seen=[21, 22])), _comment(21, "carol", body([1, 1]))]},
        "claim-intact-thread": {"claim": text, "author": "alice", "comments": [
            _comment(22, "dave", body([1, 1])), _comment(30, "bob", body([1, 1], seen=[21, 22])),
            _comment(21, "carol", body([1, 1]))]},
        "claim-self-hosted": {"claim": canonical(self_hosted), "comments": [], "author": "alice"},
        "claim-hostile-extra-field": {"claim": canonical({**claim, "base_url": "http://evil"}), "comments": [],
                                      "author": "alice"},
        "claim-hostile-provider": {"claim": canonical({**claim, "setup": {**claim["setup"], "roles": {
            **claim["setup"]["roles"], "critic": {**claim["setup"]["roles"]["critic"], "provider": "openai_compatible"}}}}),
            "comments": [], "author": "alice"},
    }  # fmt: skip


def replay_claim(vector: dict[str, Any]) -> dict[str, Any]:
    """What this engine says about a claim vector's claim and thread (or the error it refuses it with)."""
    from llm_arena.claims import ClaimError, check_claim, trust_stats  # noqa: PLC0415

    try:
        check = check_claim(str(vector["claim"]))
    except ClaimError as exc:
        return {"error": str(exc)}
    stats = trust_stats(check, vector.get("comments", []), author=str(vector["author"]), total=vector.get("total"))
    return {
        "claim_hash": check.claim_hash, "state": check.state, "swappable_roles": check.swappable_roles,
        "stats": json.loads(stats.model_dump_json()),
    }  # fmt: skip


def claim_vectors() -> dict[str, dict[str, Any]]:
    return {name: {"kind": "claim", "input": vector, "expected": replay_claim(vector)}
            for name, vector in claim_vector_inputs().items()}  # fmt: skip
