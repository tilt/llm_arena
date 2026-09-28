"""Scenario: constrained writing with self- or cross-model reflection.

Each brief carries verifiable constraints (word limits, required facts, forbidden claims,
format), so reviewer usefulness can be scored with code: did the critic flag a draft that broke
constraints, and did the revision fix it without breaking something else? Quality beyond the
constraints goes to the rubric judge and pairwise arena battles.
"""

from __future__ import annotations

import re
from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.judge import Criterion, Rubric, RubricJudgeEvaluator
from llm_arena.llm.client import system, user
from llm_arena.patterns.reflection import Critique, llm_critique, reflect
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.brief import Brief, TaskView, bullet
from llm_arena.scenarios.workflow import Workflow, reflection

TASKS: list[dict[str, Any]] = [
    {
        "id": "battery_swap_faq",
        "prompt": "Write the FAQ answer to 'How does the Veloria e-bike battery swap work?' for our website.",
        "data": {
            "facts": [
                "Batteries can be swapped at any of the 6 Veloria stations.",
                "A swap is free for members and costs EUR 2 otherwise.",
                "Swaps take under 2 minutes.",
                "Never open the battery casing yourself.",
            ],
            "checks": {
                "max_words": 120,
                "min_words": 50,
                "must_include": [["6", "six"], ["2 minutes", "two minutes"], ["eur 2", "€2", "2 eur", "2 euro"]],
                "must_not_include": ["guarantee", "100%"],
                "format": "paragraph",
            },
        },
    },
    {
        "id": "incident_update",
        "prompt": "Write a status-page update about this morning's booking outage for Quillon Studio's scheduling app.",
        "data": {
            "facts": [
                "Bookings failed between 07:40 and 08:25 CET.",
                "Cause: an expired TLS certificate on the payments gateway.",
                "No data was lost.",
                "Affected customers will not be charged for failed attempts.",
                "A certificate-expiry alert has been added.",
            ],
            "checks": {
                "max_words": 110,
                "min_words": 40,
                "must_include": [
                    ["07:40"],
                    ["08:25"],
                    ["certificate"],
                    ["not be charged", "won't be charged", "will not be charged", "no charge"],
                ],
                "must_not_include": ["hack", "breach", "sorry for any inconvenience"],
                "format": "paragraph",
            },
        },
    },
    {
        "id": "release_notes",
        "prompt": "Write release notes for version 3.2 of the Tern note-taking app as a bulleted list.",
        "data": {
            "facts": [
                "Offline mode for notes and attachments.",
                "Search is now about 3x faster.",
                "New dark theme 'Dusk'.",
                "Fixed: sync conflicts duplicated notes.",
            ],
            "checks": {
                "max_words": 90,
                "min_words": 20,
                "must_include": [["offline"], ["dusk"], ["3x", "three times"], ["sync"]],
                "must_not_include": ["revolutionary", "best ever"],
                "format": "bullets",
            },
        },
    },
    {
        "id": "workshop_invite",
        "prompt": "Write a short email inviting colleagues to the internal 'Prompt Craft' workshop.",
        "data": {
            "facts": [
                "Thursday 21 May 2026, 14:00-16:00.",
                "Room Tidewater, 2nd floor.",
                "Bring a laptop.",
                "Maximum 16 participants; sign up via the intranet form.",
            ],
            "checks": {
                "max_words": 100,
                "min_words": 40,
                "must_include": [["21 may"], ["14:00"], ["tidewater"], ["16"]],
                "must_not_include": ["mandatory"],
                "format": "email",
            },
        },
    },
]

WRITING_RUBRIC = Rubric(
    name="writing_quality",
    criteria=[
        Criterion(name="accuracy", description="States the given facts correctly and adds no invented facts."),
        Criterion(name="clarity", description="Easy to read for the intended audience; well structured."),
        Criterion(name="tone", description="Tone fits the medium (website FAQ, status page, release notes, email)."),
    ],
)


def constraint_failures(text: str, checks: dict[str, Any]) -> list[str]:
    lowered = text.lower()
    words = len(re.findall(r"\b\w[\w'’-]*\b", text))
    failures = []
    if words > checks["max_words"]:
        failures.append(f"{words} words > {checks['max_words']}")
    if words < checks["min_words"]:
        failures.append(f"{words} words < {checks['min_words']}")
    failures += [
        f"missing {group[0]!r}" for group in checks["must_include"] if not any(o.lower() in lowered for o in group)
    ]
    failures += [f"contains {phrase!r}" for phrase in checks["must_not_include"] if phrase.lower() in lowered]
    bullets = sum(1 for line in text.splitlines() if re.match(r"\s*([-*•]|\d+\.)\s", line))
    if checks["format"] == "bullets" and bullets < 3:
        failures.append("not a bulleted list")
    if checks["format"] == "email" and not re.search(r"^\s*(hi|hello|dear|hey)\b", lowered, re.MULTILINE):
        failures.append("no email greeting")
    return failures


def _checks_text(checks: dict[str, Any]) -> str:
    include = "; ".join(" or ".join(repr(o) for o in group) for group in checks["must_include"])
    return (
        f"{checks['min_words']}-{checks['max_words']} words; format: {checks['format']}; must mention: {include}; "
        f"must not contain: {', '.join(repr(p) for p in checks['must_not_include'])}."
    )


@register
class ReflectionWriting(Scenario):
    name = "reflection_writing"
    title = "Constrained writing with a critic"
    tokens_per_trial = 3000
    pattern = "reflection"
    description = "Constrained writing; a critic (same or other model) reviews; constraints are checked by code."
    roles = [
        RoleRequirement("writer", "drafts and revises"),
        RoleRequirement("critic", "reviews drafts against the brief", fallback="writer"),
    ]
    default_params = {"reflection_rounds": 1, "show_constraints_to_critic": True}
    pass_criteria = ["constraints_ok"]
    open_ended = True
    pairwise_criteria = "Accuracy against the facts, clarity, and fitting tone for the medium."

    def load_tasks(self) -> list[Task]:
        return [Task.model_validate(entry) for entry in TASKS]

    def fixtures(self) -> dict[str, Any]:
        return {"rubrics.json": [WRITING_RUBRIC.model_dump()]}

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        writer, critic = models["writer"], models.get("critic", "writer")
        facts = "\n".join(f"- {fact}" for fact in task.data["facts"])
        brief = f"{task.prompt}\n\nFacts to use:\n{facts}\n\nRequirements: {_checks_text(task.data['checks'])}"
        rules = system("You are a professional writer. Return only the requested text, no preamble.")

        async def draft() -> str:
            return (await writer.complete([rules, user(brief)])).content

        async def critique(text: str, _round: int) -> Critique:
            requirements = brief if ctx.params["show_constraints_to_critic"] else f"{task.prompt}\n\nFacts:\n{facts}"
            return await llm_critique(
                critic,
                [
                    system(
                        "You are an exacting editor. Check the draft against every requirement and fact. Accept only "
                        "if nothing must change."
                    ),
                    user(f"Brief:\n{requirements}\n\nDraft:\n{text}"),
                ],
            )

        async def revise(text: str, review: Critique, _round: int) -> str:
            issues = "\n- ".join(review.issues or [review.summary])
            return (
                await writer.complete(
                    [rules, user(f"{brief}\n\nYour draft:\n{text}\n\nEditor's notes:\n- {issues}\n\nRewrite the text.")]
                )
            ).content

        outcome = await reflect(
            draft=draft, critique=critique, revise=revise, rounds=ctx.params["reflection_rounds"], trace=ctx.trace
        )
        return TrialOutput(
            final=outcome.final, extras={"drafts": outcome.drafts, "verdicts": [c.verdict for c in outcome.critiques]}
        )

    def brief(self) -> Brief:
        return Brief(
            summary="Constrained writing with an editor in the loop: can a critic get a draft to meet every "
            "requirement (length, facts, forbidden phrases, format)?",
            environment="A brief with facts to use and verifiable requirements; no tools.",
            criteria={"constraints_ok": "every requirement checked by code: word range, required facts, "
                      "forbidden phrases, format"},
            measured=["critic precision and recall on the drafts", "writing_quality: a judge rubric (with a judge)",
                      "pairwise arena battles between configs (with a judge)"],
            compare=["reflection_rounds: 0 vs 1", "show_constraints_to_critic: does the editor need the rules?"],
        )  # fmt: skip

    def describe(self, task: Task) -> TaskView:
        checks = task.data["checks"]
        rules = []
        if "min_words" in checks or "max_words" in checks:
            rules.append(f"{checks.get('min_words', 0)}–{checks.get('max_words', '∞')} words")
        rules += ["mentions " + " or ".join(f"“{a}”" for a in group) for group in checks.get("must_include", [])]
        rules += [f"never says “{phrase}”" for phrase in checks.get("forbidden", [])]
        if fmt := checks.get("format"):
            rules.append(f"format: {fmt}")
        return TaskView(id=task.id, prompt=task.prompt, tags=task.tags, expected=[
            bullet("Requirements (checked by code)", rules), bullet("Facts to use", task.data["facts"]),
        ])  # fmt: skip

    def workflow(self) -> Workflow:
        return reflection(generator="writer", critic="critic", draft="Draft the text", critique="Editor checks the draft",
                          revise="Rewrite", evidence="draft")  # fmt: skip

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [FunctionEvaluator("constraints", score_writing), RubricJudgeEvaluator(WRITING_RUBRIC)]


def score_writing(ctx: EvalContext) -> list[Score]:
    checks = ctx.task.data["checks"]
    drafts, verdicts = ctx.output.extras["drafts"], ctx.output.extras["verdicts"]
    draft_failures, final_failures = constraint_failures(drafts[0], checks), constraint_failures(drafts[-1], checks)
    scores = [
        Score(
            name="draft_constraints_ok",
            value=float(not draft_failures),
            level="step",
            passed=not draft_failures,
            rationale="; ".join(draft_failures),
        ),
        Score(
            name="constraints_ok",
            value=float(not final_failures),
            level="e2e",
            passed=not final_failures,
            rationale="; ".join(final_failures) or "all constraints met",
        ),
        Score(name="regressed", value=float(not draft_failures and bool(final_failures)), level="e2e"),
    ]
    if verdicts:
        flagged = verdicts[0] == "revise"
        scores += [
            Score(name="critic_tp", value=float(flagged and bool(draft_failures)), level="step"),
            Score(name="critic_fp", value=float(flagged and not draft_failures), level="step"),
            Score(name="critic_fn", value=float(not flagged and bool(draft_failures)), level="step"),
        ]
    return scores
