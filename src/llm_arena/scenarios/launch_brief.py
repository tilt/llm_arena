"""Scenario: product-launch brief by a team (orchestrator + researcher, analyst, copywriter) with typed
handoffs — versus a single agent with all tools (`mode: single_agent`), the budget-matched baseline.

The data is built so there is one defensible product choice: the trend evidence from reliable
sources plus catalog constraints (stock, weight) single out one SKU; a low-quality blog pushes
an unsupported trend. Grading combines code checks (SKU, constraints, misinformation) with an
optional rubric judge.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput, ratio_score
from llm_arena.eval.judge import Criterion, Rubric, RubricJudgeEvaluator
from llm_arena.eval.trace_checks import ToolHygieneEvaluator
from llm_arena.llm.client import system, user
from llm_arena.mocks.search import CorpusSearch, Document
from llm_arena.patterns.multi_agent import Worker, orchestrate
from llm_arena.patterns.roles import RoleModels
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.research_report import search_tools
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.registry import Tool, ToolRegistry, tool

TREND_DOCS = [
    Document(
        "trend-1",
        "Outdoor retail report 2026: the ultralight overnighter",
        "Searches for 'ultralight tent' rose 64% "
        "year on year; buyers aged 25-34 lead the shift and most want shelters under 1 kg.",
        "https://outdoor-retail-institute.test/2026",
        "2026-03-10",
        {"tier": "high"},
    ),
    Document(
        "trend-2",
        "Survey: repairability sways gear buyers",
        "58% of surveyed hikers say a repair programme makes them "
        "more likely to buy a product; the effect is strongest for tents and jackets.",
        "https://calvoria-academy.test/gear-survey",
        "2026-02-01",
        {"tier": "high"},
    ),
    Document(
        "trend-3",
        "Commuters want rain-ready packs",
        "Demand for waterproof commuter backpacks grew 22% in Westmarch cities last autumn.",
        "https://westmarch-daily.test/commuter-packs",
        "2025-11-12",
        {"tier": "medium"},
    ),
    Document(
        "trend-4",
        "NEON IS BACK and it's HUGE",
        "Neon outdoor gear is up 300% this summer, everyone says so!",
        "https://greentechbuzz.test/neon",
        "2026-04-01",
        {"tier": "low"},
    ),
]

CATALOG = [
    {
        "sku": "FS-TENT-UL1",
        "name": "Ridgeline UL1 tent",
        "category": "tent",
        "weight_g": 890,
        "stock": 420,
        "price_eur": 329,
        "repair_programme": True,
    },
    {
        "sku": "FS-TENT-2P",
        "name": "Basecamp 2P tent",
        "category": "tent",
        "weight_g": 2400,
        "stock": 800,
        "price_eur": 249,
        "repair_programme": True,
    },
    {
        "sku": "FS-QUILT-UL",
        "name": "Featherline quilt",
        "category": "sleep",
        "weight_g": 620,
        "stock": 60,
        "price_eur": 279,
        "repair_programme": False,
    },
    {
        "sku": "FS-PACK-CMT",
        "name": "Drizzle commuter pack",
        "category": "pack",
        "weight_g": 1100,
        "stock": 650,
        "price_eur": 129,
        "repair_programme": True,
    },
    {
        "sku": "FS-JKT-NEON",
        "name": "Volt neon shell",
        "category": "jacket",
        "weight_g": 380,
        "stock": 900,
        "price_eur": 189,
        "repair_programme": False,
    },
]

TASKS = [
    {
        "id": "summer_launch",
        "prompt": "Prepare the launch brief for Fjellstrand's summer campaign: pick ONE product to "
        "feature (it needs at least 100 units in stock), justify the choice with market evidence, and provide a headline "
        "and a tagline of at most 12 words.",
        "data": {"gold_sku": "FS-TENT-UL1", "banned_claims": ["300%"]},
    },
    {
        "id": "summer_launch_repair",
        "prompt": "Fjellstrand wants a summer campaign that highlights its repair programme. "
        "Choose ONE product with a repair programme and at least 100 units in stock that best matches this year's strongest "
        "evidence-backed trend, and write a headline and a tagline (max 12 words).",
        "data": {"gold_sku": "FS-TENT-UL1", "banned_claims": ["300%"]},
    },
]


class TrendFinding(BaseModel):
    trend: str
    evidence: str = Field(description="The concrete figure or finding")
    source_id: str = Field(description="id of the document that supports it")


class TrendFindings(BaseModel):
    findings: list[TrendFinding]


class ProductPick(BaseModel):
    sku: str
    reason: str
    stock: int


class CampaignCopy(BaseModel):
    headline: str
    tagline: str
    body: str = Field(description="Two or three sentences")


BRIEF_RUBRIC = Rubric(
    name="brief_quality",
    criteria=[
        Criterion(
            name="evidence", description="The product choice is justified with specific, credible market evidence."
        ),
        Criterion(name="consistency", description="Product, evidence and copy fit together; no contradictions."),
        Criterion(name="copy", description="Headline and tagline are catchy, concrete and on-brand for outdoor gear."),
    ],
)

COMPOSE = (
    "Write the final launch brief in Markdown with these sections: Recommended product (name and SKU), Why (evidence with "
    "source ids in square brackets), Headline, and a line starting with 'Tagline:'. Use only facts from the team results."
)
_SKU = re.compile(r"FS-[A-Z0-9]+-[A-Z0-9]+")


def catalog_tools() -> list[Tool]:
    @tool
    def list_products() -> list[dict[str, Any]]:
        """List all catalog products with category, weight, stock, price and repair-programme flag."""
        return CATALOG

    @tool
    def get_product(sku: str) -> dict[str, Any]:
        """Return one product by SKU."""
        for product in CATALOG:
            if product["sku"] == sku:
                return product
        raise KeyError(f"unknown sku {sku}")

    return [list_products, get_product]


@register
class LaunchBrief(Scenario):
    name = "launch_brief"
    title = "Product launch team (multi-agent)"
    tokens_per_trial = 15000
    param_choices = {"mode": ["multi_agent", "single_agent"], "delegation": ["auto", "fixed"]}
    pattern = "multi_agent"
    description = "Orchestrator + researcher/analyst/copywriter with typed handoffs vs a single agent with all tools."
    roles = [
        RoleRequirement("orchestrator", "delegates and composes the brief"),
        RoleRequirement("researcher", "finds market trends", fallback="orchestrator"),
        RoleRequirement("analyst", "picks the product from the catalog", fallback="orchestrator"),
        RoleRequirement("copywriter", "writes headline and tagline", fallback="orchestrator"),
    ]
    default_params = {
        "mode": "multi_agent",
        "delegation": "auto",
        "max_turns": 8,
    }  # delegation: auto|fixed
    pass_criteria = ["correct_product", "tagline_ok", "no_misinformation"]
    open_ended = True
    pairwise_criteria = (
        "Quality of the product choice and its justification, credibility of evidence, strength of copy."
    )

    def load_tasks(self) -> list[Task]:
        return [Task.model_validate(entry) for entry in TASKS]

    def fixtures(self) -> dict[str, Any]:
        return {
            "trends.json": [asdict(doc) for doc in TREND_DOCS],
            "catalog.json": CATALOG,
            "tools.json": [t.schema() for t in [*search_tools(CorpusSearch(TREND_DOCS)), *catalog_tools()]],
            "handoff_schemas.json": {
                m.__name__: m.model_json_schema() for m in (TrendFindings, ProductPick, CampaignCopy)
            },
            "rubrics.json": [BRIEF_RUBRIC.model_dump()],
        }

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        corpus = CorpusSearch(TREND_DOCS)
        if ctx.params["mode"] == "single_agent":
            registry = ToolRegistry([*search_tools(corpus), *catalog_tools()])
            loop = await run_tool_loop(
                models["orchestrator"],
                [
                    system(f"You are a marketing strategist with research and catalog tools. {COMPOSE}"),
                    user(task.prompt),
                ],
                ToolExecutor(registry, ctx.trace, role="orchestrator"),
                max_turns=ctx.params["max_turns"] * 2,
            )
            return TrialOutput(final=loop.final, extras={"mode": "single_agent", "stop_reason": loop.stop_reason})

        workers = [
            Worker(
                "researcher",
                "finds evidence-backed market trends in reports",
                "You are a market researcher. Search "
                "the reports, read the most credible ones, and report trends with the id of the supporting document.",
                TrendFindings,
                models.get("researcher", "orchestrator"),
                ToolExecutor(ToolRegistry(search_tools(corpus)), ctx.trace, role="researcher"),
                ctx.params["max_turns"],
            ),
            Worker(
                "analyst",
                "chooses the product from the catalog that fits trends and constraints",
                "You are a "
                "merchandise analyst. Use the catalog to pick the single best product given the trends and constraints.",
                ProductPick,
                models.get("analyst", "orchestrator"),
                ToolExecutor(ToolRegistry(catalog_tools()), ctx.trace, role="analyst"),
                ctx.params["max_turns"],
            ),
            Worker(
                "copywriter",
                "writes headline, tagline and body copy for the chosen product",
                "You are a copywriter "
                "for an outdoor brand. Write vivid but truthful copy; the tagline has at most 12 words.",
                CampaignCopy,
                models.get("copywriter", "orchestrator"),
            ),
        ]
        result = await orchestrate(
            models["orchestrator"],
            workers,
            task.prompt,
            ctx.trace,
            compose_instructions=COMPOSE,
            fixed_order=["researcher", "analyst", "copywriter"] if ctx.params["delegation"] == "fixed" else None,
        )
        fetched = [
            span.input.get("doc_id")
            for span in ctx.trace.select("tool_call", name="fetch_document")
            if span.attrs.get("ok")
        ]
        return TrialOutput(
            final=result.final,
            env_state={"blackboard": result.blackboard},
            extras={
                "mode": "multi_agent",
                "rejected": result.rejected_handoffs,
                "fetched": fetched,
                "delegated": [a.worker for a in result.delegation.assignments] if result.delegation else [],
            },
        )

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [
            ToolHygieneEvaluator(),
            FunctionEvaluator("handoffs", score_handoffs),
            FunctionEvaluator("brief", score_brief),
            RubricJudgeEvaluator(BRIEF_RUBRIC),
        ]


def score_handoffs(ctx: EvalContext) -> list[Score]:
    if ctx.output.extras["mode"] != "multi_agent":
        return []
    handoffs = ctx.trace.select("handoff")
    accepted = sum(bool(span.attrs.get("accepted")) for span in handoffs)
    scores = [ratio_score("handoff_acceptance", accepted, len(handoffs), "step", empty=0.0)]
    findings = ctx.output.env_state["blackboard"].get("researcher", {}).get("findings", [])
    fetched = set(ctx.output.extras["fetched"])
    unsupported = [f for f in findings if f["source_id"] not in fetched]
    scores.append(ratio_score("unsupported_claim_rate", len(unsupported), len(findings), "step", empty=0.0))
    pick = ctx.output.env_state["blackboard"].get("analyst", {}).get("sku")
    scores.append(
        Score(
            name="analyst_pick_correct",
            value=float(pick == ctx.task.data["gold_sku"]),
            level="step",
            passed=pick == ctx.task.data["gold_sku"],
            rationale=str(pick),
        )
    )
    return scores


def score_brief(ctx: EvalContext) -> list[Score]:
    text = ctx.output.final
    skus = set(_SKU.findall(text))
    gold = ctx.task.data["gold_sku"]
    correct = skus == {gold} or (gold in skus and _recommended_line_has(text, gold))
    tagline = next(
        (
            line.split(":", 1)[1].strip(" *_\"'")
            for line in text.splitlines()
            if line.strip(" *#").lower().startswith("tagline")
        ),
        "",
    )
    tagline_words = len(tagline.split())
    banned = [claim for claim in ctx.task.data["banned_claims"] if claim in text]
    return [
        Score(
            name="correct_product", value=float(correct), level="e2e", passed=correct, rationale=f"SKUs: {sorted(skus)}"
        ),
        Score(
            name="tagline_ok",
            value=float(0 < tagline_words <= 12),
            level="e2e",
            passed=0 < tagline_words <= 12,
            rationale=f"{tagline_words} words: {tagline!r}",
        ),
        Score(
            name="no_misinformation",
            value=float(not banned),
            level="e2e",
            passed=not banned,
            rationale=f"repeated {banned}" if banned else "none",
        ),
    ]


def _recommended_line_has(text: str, sku: str) -> bool:
    return any(sku in line for line in text.splitlines() if "recommend" in line.lower())
