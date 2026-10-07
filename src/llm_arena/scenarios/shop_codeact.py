"""Scenario: customer-service tasks solved by writing Python against a shop API (code as action).

End-to-end grading compares the final shop database with the expected changes and checks the
store policy; step metrics count executions, failed executions and steps to completion.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.compare import last_number, numbers_match
from llm_arena.eval.credit import change_credit
from llm_arena.eval.trace_checks import StopReasonEvaluator
from llm_arena.mocks.shop import API_DOC, API_SOURCE, POLICY, TODAY, ShopEnvironment
from llm_arena.patterns.codeact import run_codeact
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.brief import Brief, TaskView, bullet, text
from llm_arena.scenarios.workflow import END, START, Workflow, edge, step

TASKS: list[dict[str, Any]] = [
    {
        "id": "cancel_processing",
        "prompt": "Ana Pereira (ana.pereira@mail.test) asks to cancel her order 1042.",
        "data": {
            "expect": {
                "order_status": {"1042": "cancelled"},
                "stock": {"PLT-DIN": 4, "VAS-TAL": 4},
                "refund_total": {},
                "messaged": ["ana.pereira@mail.test"],
            }
        },
    },
    {
        "id": "partial_damage_refund",
        "prompt": "Ines Moreau says one of the two mugs in order 1017 arrived broken. Handle it.",
        "data": {"expect": {"refund_total": {"1017": 18.0}, "messaged": ["ines.moreau@mail.test"]}},
    },
    {
        "id": "refund_outside_window",
        "prompt": "Rui Tanaka wants a full refund for order 1003.",
        "data": {"expect": {"refund_total": {}, "messaged": ["rui.tanaka@mail.test"]}},
    },
    {
        "id": "restock_out_of_stock",
        "prompt": "Restock every product that is out of stock to exactly 20 units.",
        "data": {"expect": {"stock": {"MUG-TID": 20, "PLT-DIN": 20}, "refund_total": {}, "messaged": []}},
    },
    {
        "id": "cancel_shipped",
        "prompt": "Tobias Klein wants to cancel order 1050.",
        "data": {
            "expect": {"order_status": {"1050": "shipped"}, "refund_total": {}, "messaged": ["tobias.klein@mail.test"]}
        },
    },
    {
        "id": "count_customer_orders",
        "prompt": "How much has ana.pereira@mail.test paid across all her orders? Just answer, change nothing.",
        "data": {"expect": {"refund_total": {}, "messaged": []}, "answer_number": 227.0},
    },
]


@register
class ShopCodeAct(Scenario):
    name = "shop_codeact"
    title = "Customer service via code actions"
    tokens_per_trial = 8000
    requires = frozenset({"sandbox"})
    pattern = "code_execution"
    description = "Customer service by writing Python against a shop API in a sandbox; graded by final DB state."
    roles = [RoleRequirement("agent", "writes and runs Python against the shop API", kind="code")]
    default_params = {"max_steps": 6, "timeout_s": 20}
    pass_criteria = ["state_correct", "policy_ok"]
    version = "2"  # 2: state_correct scores the share of expected changes made (partial credit)
    regrades_from = frozenset({"1"})  # only grading changed since

    def load_tasks(self) -> list[Task]:
        return [Task.model_validate(entry) for entry in TASKS]

    def fixtures(self) -> dict[str, Any]:
        shop = ShopEnvironment()
        return {"shop_state.json": shop.state(), "api.py": API_SOURCE.lstrip(), "api_doc.txt": API_DOC + "\n",
                "policy.txt": POLICY + "\n"}  # fmt: skip

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        shop = ShopEnvironment()
        initial = shop.state()
        result = await run_codeact(
            models["agent"],
            task.prompt,
            shop,
            ctx.require_sandbox(),
            ctx.trace,
            max_steps=ctx.params["max_steps"],
            timeout_s=ctx.params["timeout_s"],
            system_prompt=f"You are the customer-service agent of the ceramics shop Kiln & Kettle. Today is {TODAY}.\n{POLICY}",
        )
        return TrialOutput(
            final=result.final,
            env_state={"initial": initial, "final": shop.state()},
            extras={
                "stop_reason": result.stop_reason,
                "executions": result.executions,
                "failed": result.failed_executions,
            },
        )

    def brief(self) -> Brief:
        return Brief(
            summary="Code as action: the agent solves customer requests by writing Python against a shop API, "
            "and must follow the store policy although the API does not enforce it.",
            environment="A sandbox with the shop's API module and its SQLite state, which persists between steps.",
            criteria={"state_correct": "orders, refunds, stock and messages end as expected",
                      "policy_ok": "no cancellation after processing, no refund outside 30 days or above the amount paid"},
            measured=["executions and failed executions per task"],
            traps=["the API happily executes policy violations"],
        )  # fmt: skip

    def describe(self, task: Task) -> TaskView:
        expect = task.data["expect"]
        lines = [f"order {o} → {status}" for o, status in expect.get("order_status", {}).items()]
        lines += [f"refunds on order {o}: ${amount:.2f}" for o, amount in expect.get("refund_total", {}).items()]
        lines += [f"stock of {sku}: {n}" for sku, n in expect.get("stock", {}).items()]
        lines += [f"message to {who}" for who in expect.get("messaged", [])]
        expected = [bullet("Expected final state", lines or ["nothing changes"])]
        if "answer_number" in task.data:
            expected.insert(0, text("Answer", f"{task.data['answer_number']:g}"))
        return TaskView(id=task.id, prompt=task.prompt, tags=task.tags, expected=expected)

    def workflow(self) -> Workflow:
        return Workflow(
            steps=[START, step("code", "Agent writes Python", "llm", "agent", "against the shop API"),
                   step("exec", "Execute in the sandbox", "code", description="state persists between steps"), END],
            edges=[edge("start", "code"), edge("code", "exec"), edge("exec", "code", "output", loop=True),
                   edge("code", "end", "FINAL ANSWER")],
        )  # fmt: skip

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [
            StopReasonEvaluator(),
            FunctionEvaluator("shop_steps", _step_scores),
            FunctionEvaluator("shop_state", check_shop),
        ]


def _step_scores(ctx: EvalContext) -> list[Score]:
    executions, failed = ctx.output.extras["executions"], ctx.output.extras["failed"]
    return [
        Score(name="executions", value=float(executions), level="step"),
        Score(
            name="execution_success_rate", value=(executions - failed) / executions if executions else 0.0, level="step"
        ),
    ]


def check_shop(ctx: EvalContext) -> list[Score]:
    expect = ctx.task.data["expect"]
    initial, final = ctx.output.env_state["initial"], ctx.output.env_state["final"]
    keys = _check_keys(expect, initial, final)
    checks = shop_checks(expect, initial, final, keys)
    problems = [problem for problem in checks.values() if problem]
    before = {key: problem is None for key, problem in shop_checks(expect, initial, initial, keys).items()}
    credit = change_credit(before, {key: problem is None for key, problem in checks.items()})

    violations = _policy_violations(initial, final)
    scores = [
        Score(
            name="state_correct",
            value=1.0 if not problems else credit,
            level="e2e",
            passed=not problems,
            rationale="; ".join(problems) or "state matches",
        ),
        Score(
            name="policy_ok",
            value=float(not violations),
            level="e2e",
            passed=not violations,
            rationale="; ".join(violations) or "no violations",
        ),
    ]
    if "answer_number" in ctx.task.data:
        ok = numbers_match(last_number(ctx.output.final), ctx.task.data["answer_number"], rel_tol=1e-3)
        scores.append(Score(name="answer_correct", value=float(ok), level="e2e", passed=ok))
    return scores


def _refund_totals(state: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for refund in state["refunds"]:
        totals[str(refund["order_id"])] = totals.get(str(refund["order_id"]), 0.0) + refund["amount"]
    return {order_id: round(total, 2) for order_id, total in totals.items()}


def _check_keys(expect: dict[str, Any], initial: dict[str, Any], final: dict[str, Any]) -> dict[str, list[str]]:
    """What to check in any state: everything expected plus everything either state touched."""
    return {
        "stock": sorted({p["sku"] for p in initial["products"]} | set(expect.get("stock", {}))),
        "refunds": sorted(set(_refund_totals(initial)) | set(_refund_totals(final)) | set(expect.get("refund_total", {}))),
        "messaged": sorted({m["customer_email"] for state in (initial, final) for m in state["messages"]}
                           | set(expect.get("messaged", []))),
    }  # fmt: skip


def shop_checks(
    expect: dict[str, Any], initial: dict[str, Any], state: dict[str, Any], keys: dict[str, list[str]]
) -> dict[str, str | None]:
    """Keyed state checks: None when met, else the problem.

    Stock must not change except where the task expects it (cancellations restock their items); refunds and
    messages must match exactly, so an extra one is a failed check too.
    """
    checks: dict[str, str | None] = {}
    orders = {str(o["order_id"]): o for o in state["orders"]}
    for order_id, status in expect.get("order_status", {}).items():
        actual = orders[order_id]["status"]
        checks[f"status:{order_id}"] = None if actual == status else f"order {order_id} is {actual}, expected {status}"
    stock = {p["sku"]: p["stock"] for p in state["products"]}
    initial_stock = {p["sku"]: p["stock"] for p in initial["products"]}
    for sku in keys["stock"]:
        want = expect.get("stock", {}).get(sku, initial_stock.get(sku))
        if stock.get(sku) != want:
            checks[f"stock:{sku}"] = (
                f"{sku} stock {stock.get(sku)}, expected {want}" if sku in expect.get("stock", {})
                else f"unexpected stock change: {sku}"
            )  # fmt: skip
        else:
            checks[f"stock:{sku}"] = None
    refunds, wanted_refunds = _refund_totals(state), expect.get("refund_total", {})
    for order_id in keys["refunds"]:
        have, want = refunds.get(order_id, 0.0), float(wanted_refunds.get(order_id, 0.0))
        checks[f"refund:{order_id}"] = (
            None if abs(have - want) <= 0.005 else f"order {order_id} refunded {have:.2f}, expected {want:.2f}"
        )
    messaged, wanted_messages = {m["customer_email"] for m in state["messages"]}, set(expect.get("messaged", []))
    for email in keys["messaged"]:
        if (email in messaged) == (email in wanted_messages):
            checks[f"message:{email}"] = None
        else:
            checks[f"message:{email}"] = (
                f"no message to {email}" if email in wanted_messages else f"unexpected message to {email}"
            )
    return checks


def _policy_violations(initial: dict[str, Any], final: dict[str, Any]) -> list[str]:
    before = {o["order_id"]: o for o in initial["orders"]}
    violations = []
    for order in final["orders"]:
        if order["status"] == "cancelled" and before[order["order_id"]]["status"] != "processing":
            violations.append(f"cancelled order {order['order_id']} in status {before[order['order_id']]['status']}")
    refunded: dict[int, float] = {}
    for refund in final["refunds"]:
        refunded[refund["order_id"]] = refunded.get(refund["order_id"], 0.0) + refund["amount"]
    for order_id, amount in refunded.items():
        order = before[order_id]
        if amount > order["paid"] + 1e-6:
            violations.append(f"refunded {amount} on order {order_id} which paid {order['paid']}")
        if order["delivered_on"] is None or _days_between(order["delivered_on"], TODAY) > 30:
            violations.append(f"refund on order {order_id} outside the 30-day window")
    return violations


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days
