"""Scenario: customer-service tasks solved by writing Python against a shop API (code as action).

End-to-end grading compares the final shop database with the expected changes and checks the
store policy; step metrics count executions, failed executions and steps to completion.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.compare import last_number, numbers_match
from llm_arena.eval.trace_checks import StopReasonEvaluator
from llm_arena.mocks.shop import API_DOC, API_SOURCE, POLICY, TODAY, ShopEnvironment
from llm_arena.patterns.codeact import run_codeact
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
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
    roles = [RoleRequirement("agent", "writes and runs Python against the shop API")]
    default_params = {"max_steps": 6, "timeout_s": 20}
    pass_criteria = ["state_correct", "policy_ok"]

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
    problems: list[str] = []
    orders = {str(o["order_id"]): o for o in final["orders"]}
    stock = {p["sku"]: p["stock"] for p in final["products"]}
    for order_id, status in expect.get("order_status", {}).items():
        if orders[order_id]["status"] != status:
            problems.append(f"order {order_id} is {orders[order_id]['status']}, expected {status}")
    for sku, quantity in expect.get("stock", {}).items():
        if stock[sku] != quantity:
            problems.append(f"{sku} stock {stock[sku]}, expected {quantity}")
    refunds: dict[str, float] = {}
    for refund in final["refunds"]:
        refunds[str(refund["order_id"])] = refunds.get(str(refund["order_id"]), 0.0) + refund["amount"]
    if {k: round(v, 2) for k, v in refunds.items()} != expect.get("refund_total", {}):
        problems.append(f"refunds {refunds}, expected {expect.get('refund_total', {})}")
    messaged = sorted({m["customer_email"] for m in final["messages"]})
    if messaged != sorted(expect.get("messaged", [])):
        problems.append(f"messaged {messaged}, expected {expect.get('messaged', [])}")
    # Stock must not change except where the task expects it (cancellations restock their items).
    initial_stock = {p["sku"]: p["stock"] for p in initial["products"]}
    stray = [sku for sku in stock if stock[sku] != initial_stock[sku] and sku not in expect.get("stock", {})]
    if stray:
        problems.append(f"unexpected stock changes: {stray}")

    violations = _policy_violations(initial, final)
    scores = [
        Score(
            name="state_correct",
            value=float(not problems),
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
