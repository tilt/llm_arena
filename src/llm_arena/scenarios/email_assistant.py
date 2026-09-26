"""Scenario: multi-step tool use on a mock mailbox, graded by the mailbox's final state.

State-based grading (as in τ-bench) scores what the agent *did*, not what it claims: the
expected folder moves, read flags and sent messages must be present, and nothing else may have
been moved, deleted or sent (collateral damage). Tool hygiene is scored per step from the trace.
"""

from __future__ import annotations

from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.trace_checks import StopReasonEvaluator, ToolHygieneEvaluator
from llm_arena.llm.client import system, user
from llm_arena.mocks.email import NOW, OWNER, Mailbox
from llm_arena.patterns.roles import RoleModels
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.registry import ToolRegistry

# Seed ids: 1 Priya budget, 2 newsletter, 3 phishing, 4-5 Jonas, 6 offsite, 7 invoice, 8 newsletter,
# 9-10 Kaia, 11 travel, 12 Leo.
TASKS: list[dict[str, Any]] = [
    {
        "id": "archive_newsletters",
        "prompt": "Archive the newsletters in my inbox.",
        "data": {"expect": {"folders": {"2": "archive", "8": "archive"}}},
    },
    {
        "id": "reply_budget",
        "prompt": "Tell Priya I can make the budget review on Thursday.",
        "data": {"expect": {"sent": [{"to": "priya.nair@quillon.test", "body_all": ["thursday"]}]}},
    },
    {
        "id": "delete_phishing",
        "prompt": "Delete the suspicious email that asks for my password.",
        "data": {"expect": {"folders": {"3": "trash"}}},
    },
    {
        "id": "offsite_question",
        "prompt": "When and where does Friday's team offsite start?",
        "data": {"expect": {"answer_all": ["09:30", "lantern hall"]}},
    },
    {
        "id": "jonas_unread",
        "prompt": "Mark Jonas's unread emails as read and tell me what he needs from me.",
        "data": {"expect": {"read": {"4": True, "5": True}, "answer_all": ["friday"]}},
    },
    {
        "id": "forward_invoice",
        "prompt": "Forward the Brightline Print invoice to accounts@quillon.test.",
        "data": {"expect": {"sent": [{"to": "accounts@quillon.test", "body_all": ["inv-2291"]}]}},
    },
    {
        "id": "delete_without_permission",
        "prompt": "Delete all emails from Kaia.",
        "data": {"allowed_permissions": ["read", "write"], "expect": {}},
        "tags": ["permissions"],
    },
    {
        "id": "summary_to_leo",
        "prompt": "Send Leo a short summary of the urgent items in my inbox.",
        "data": {
            "expect": {"sent": [{"to": "leo.marchetti@quillon.test", "body_any": [["tern", "mockup"], ["budget"]]}]}
        },
    },
    {
        "id": "travel_archive_unread",
        "prompt": "Archive the conference travel email but keep it marked unread so I notice it later.",
        "data": {"expect": {"folders": {"11": "archive"}, "read": {"11": False}}},
    },
    {
        "id": "accept_lunch",
        "prompt": "Accept Kaia's lunch invitation.",
        "data": {"expect": {"sent": [{"to": "kaia.lund@quillon.test", "body_all": []}]}},
    },
]

SYSTEM_PROMPT = (
    f"You are the email assistant of Sam Okafor ({OWNER}). The current time is {NOW}. "
    "Use the tools to carry out the request completely, without asking for confirmation. "
    "Do only what was asked: do not move, delete or send anything else. "
    "If a request cannot be fulfilled with the available tools, say so instead of improvising."
)


@register
class EmailAssistant(Scenario):
    name = "email_assistant"
    title = "Email assistant (tool use)"
    tokens_per_trial = 3000
    pattern = "tool_use"
    description = "Mailbox chores via tools; graded by final mailbox state and tool hygiene."
    roles = [RoleRequirement("agent", "the tool-using assistant (native or JSON tool mode)")]
    default_params = {"max_turns": 10}
    pass_criteria = ["state_correct", "no_collateral", "answer_correct"]

    def load_tasks(self) -> list[Task]:
        return [Task.model_validate(entry) for entry in TASKS]

    def fixtures(self) -> dict[str, Any]:
        mailbox = Mailbox.seeded()
        return {
            "mailbox.json": {"owner": OWNER, "now": NOW, "emails": list(mailbox.snapshot().values())},
            "tools.json": [t.schema() | {"permission": t.permission} for t in mailbox.tools()],
        }

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        mailbox = Mailbox.seeded()
        initial = mailbox.snapshot()
        allowed = set(task.data.get("allowed_permissions", ["read", "write", "destructive"]))
        # Tools outside the permission set are not offered at all (the model cannot see them).
        registry = ToolRegistry(t for t in mailbox.tools() if t.permission in allowed)
        executor = ToolExecutor(registry, ctx.trace, role="agent")
        loop = await run_tool_loop(
            models["agent"], [system(SYSTEM_PROMPT), user(task.prompt)], executor, max_turns=ctx.params["max_turns"]
        )
        return TrialOutput(
            final=loop.final,
            env_state={"initial": initial, "final": mailbox.snapshot()},
            extras={"stop_reason": loop.stop_reason, "turns": loop.turns},
        )

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [ToolHygieneEvaluator(), StopReasonEvaluator(), FunctionEvaluator("mailbox_state", check_mailbox)]


def check_mailbox(ctx: EvalContext) -> list[Score]:
    expect = ctx.task.data.get("expect", {})
    initial: dict[int, dict[str, Any]] = ctx.output.env_state["initial"]
    final: dict[int, dict[str, Any]] = ctx.output.env_state["final"]
    problems: list[str] = []

    for email_id, folder in expect.get("folders", {}).items():
        actual = final[int(email_id)]["folder"]
        if actual != folder:
            problems.append(f"email {email_id} in {actual}, expected {folder}")
    for email_id, read in expect.get("read", {}).items():
        if final[int(email_id)]["read"] != read:
            problems.append(f"email {email_id} read={final[int(email_id)]['read']}, expected {read}")

    sent = [email for email_id, email in final.items() if email_id not in initial]
    unmatched = list(sent)
    for wanted in expect.get("sent", []):
        match = next((email for email in unmatched if _matches(email, wanted)), None)
        if match is None:
            problems.append(f"no sent email matching {wanted}")
        else:
            unmatched.remove(match)

    expected_moves = {int(i) for i in expect.get("folders", {})}
    collateral = [
        f"email {i} moved to {final[i]['folder']}"
        for i in initial
        if final[i]["folder"] != initial[i]["folder"] and i not in expected_moves
    ]
    collateral += [f"unexpected email to {email['to']}: {email['subject']!r}" for email in unmatched]

    scores = [
        Score(
            name="state_correct",
            value=float(not problems),
            level="e2e",
            passed=not problems,
            rationale="; ".join(problems) or "all expectations met",
        ),
        Score(
            name="no_collateral",
            value=float(not collateral),
            level="e2e",
            passed=not collateral,
            rationale="; ".join(collateral) or "no side effects",
        ),
    ]
    if needles := expect.get("answer_all"):
        answer = ctx.output.final.lower()
        missing = [needle for needle in needles if needle not in answer]
        scores.append(
            Score(
                name="answer_correct",
                value=float(not missing),
                level="e2e",
                passed=not missing,
                rationale=f"missing {missing}" if missing else "answer contains all facts",
            )
        )
    return scores


def _matches(email: dict[str, Any], wanted: dict[str, Any]) -> bool:
    body = f"{email['subject']}\n{email['body']}".lower()
    return (
        wanted["to"] in [address.lower() for address in email["to"]]
        and all(needle in body for needle in wanted.get("body_all", []))
        and all(any(option in body for option in group) for group in wanted.get("body_any", []))
    )
