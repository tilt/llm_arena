"""Scenario: research agent (tool use) → cited report (writer) → review and revision (reflection).

Component evals score retrieval on its own (source quality, recall of authoritative documents)
separately from writing (fact recall, misinformation, citation validity), so a regression can
be located in the step that caused it.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput, ratio_score
from llm_arena.eval.judge import Criterion, Rubric, RubricJudgeEvaluator
from llm_arena.eval.trace_checks import ToolHygieneEvaluator
from llm_arena.llm.client import system, user
from llm_arena.mocks.research_corpus import TOPICS, corpus_documents
from llm_arena.mocks.search import CorpusSearch, SearchBackend
from llm_arena.patterns.reflection import Critique, llm_critique, reflect
from llm_arena.patterns.roles import RoleModels
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.workflow import END, START, Workflow, edge, reflection, step
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.registry import Tool, ToolRegistry, tool

_CITATION = re.compile(r"\[([a-z0-9_.\-]+-\d+)\]", re.IGNORECASE)

REPORT_RUBRIC = Rubric(
    name="report_quality",
    criteria=[
        Criterion(
            name="groundedness", description="Every factual claim is supported by a cited source; no invented figures."
        ),
        Criterion(name="coverage", description="Answers the question with the key facts (numbers, dates, actors)."),
        Criterion(
            name="source_judgement", description="Prefers authoritative sources and flags or ignores dubious ones."
        ),
        Criterion(name="clarity", description="Concise, well organised, readable by a non-specialist."),
    ],
)


def search_tools(backend: SearchBackend) -> list[Tool]:
    @tool
    async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search for sources; returns id, title, url, publication date and a snippet per hit."""
        return await backend.search(query, max_results=max_results)

    @tool
    async def fetch_document(doc_id: str) -> dict[str, Any]:
        """Fetch the full text of a source by its id."""
        return await backend.fetch(doc_id)

    return [search, fetch_document]


@register
class ResearchReport(Scenario):
    name = "research_report"
    title = "Research report with sources"
    tokens_per_trial = 12000
    param_choices = {"backend": ["corpus", "tavily", "arxiv"]}
    pattern = "tool_use+reflection"
    description = "Research with search tools, write a cited report, review and revise it."
    roles = [
        RoleRequirement("researcher", "searches and reads sources"),
        RoleRequirement("writer", "writes and revises the cited report", fallback="researcher"),
        RoleRequirement("reviewer", "critiques the report against its sources", fallback="writer"),
    ]
    default_params = {
        "max_turns": 8,
        "reflection_rounds": 1,
        "backend": "corpus",
    }  # corpus|tavily|arxiv
    pass_criteria = ["fact_recall", "no_misinformation", "citation_validity"]
    open_ended = True
    pairwise_criteria = "Accuracy of facts, use of authoritative sources, citations, clarity."

    def load_tasks(self) -> list[Task]:
        documents = corpus_documents()
        return [
            Task(
                id=topic.id,
                prompt=topic.question,
                data={
                    "facts": [
                        {"key": f.key, "statement": f.statement, "patterns": list(f.patterns)} for f in topic.facts
                    ],
                    "wrong_claims": list(topic.wrong_claims),
                    "gold_docs": [d.id for d in documents if d.meta["topic"] == topic.id and d.meta["tier"] == "high"],
                    "reference": [f.statement for f in topic.facts],
                },
            )
            for topic in TOPICS
        ]

    def fixtures(self) -> dict[str, Any]:
        documents = corpus_documents()
        return {
            "corpus.json": [asdict(doc) for doc in documents],
            "tools.json": [t.schema() for t in search_tools(CorpusSearch(documents))],
            "rubrics.json": [REPORT_RUBRIC.model_dump()],
        }

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        backend = _backend(ctx)
        executor = ToolExecutor(ToolRegistry(search_tools(backend)), ctx.trace, role="researcher")
        research = await run_tool_loop(
            models["researcher"],
            [
                system(
                    "You are a careful research assistant. Find and read the most authoritative sources for the question "
                    "(official statistics, agencies, peer-reviewed journals) and be sceptical of sensational sites. "
                    "Finish with research notes: key facts, each followed by the source id in square brackets."
                ),
                user(task.prompt),
            ],
            executor,
            max_turns=ctx.params["max_turns"],
        )
        writer, reviewer = models.get("writer", "researcher"), models.get("reviewer", "writer")
        brief = f"Question: {task.prompt}\n\nResearch notes:\n{research.final}"
        writing_rules = (
            "Write a report of at most 200 words answering the question. Cite every factual claim with the source id "
            "in square brackets, e.g. [doc-1]. Use only facts from the notes."
        )

        async def draft() -> str:
            return (await writer.complete([system(writing_rules), user(brief)])).content

        async def critique(report: str, _round: int) -> Critique:
            return await llm_critique(
                reviewer,
                [
                    system(
                        "You review research reports for unsupported claims, missing key facts, weak sources and clarity."
                    ),
                    user(f"{brief}\n\nReport:\n{report}"),
                ],
            )

        async def revise(report: str, review: Critique, _round: int) -> str:
            issues = "\n- ".join(review.issues or [review.summary])
            prompt = f"{brief}\n\nCurrent report:\n{report}\n\nReviewer issues:\n- {issues}\n\nRewrite the report."
            return (await writer.complete([system(writing_rules), user(prompt)])).content

        outcome = await reflect(
            draft=draft, critique=critique, revise=revise, rounds=ctx.params["reflection_rounds"], trace=ctx.trace
        )
        fetched = [
            span.input.get("doc_id")
            for span in ctx.trace.select("tool_call", name="fetch_document")
            if span.ok and span.attrs.get("ok")
        ]
        return TrialOutput(
            final=outcome.final,
            extras={
                "draft": outcome.initial,
                "notes": research.final,
                "fetched": fetched,
                "stop_reason": research.stop_reason,
            },
        )

    def workflow(self) -> Workflow:
        writing = reflection(generator="writer", critic="reviewer", draft="Write the report",
                             critique="Reviewer checks sources and claims", revise="Revise the report")  # fmt: skip
        research = [step("research", "Researcher searches and reads", "llm", "researcher"),
                    step("search", "Search + fetch (corpus / web / arXiv)", "tool")]  # fmt: skip
        steps = [START, *research, *[s for s in writing.steps if s.id not in ("start", "end")], END]
        edges = [edge("start", "research"), edge("research", "search", "tool call"),
                 edge("search", "research", "results", loop=True), edge("research", "draft", "notes"),
                 *[e for e in writing.edges if e.source != "start"]]  # fmt: skip
        return Workflow(steps=steps, edges=edges)

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [
            ToolHygieneEvaluator(),
            FunctionEvaluator("retrieval", score_retrieval),
            FunctionEvaluator("report_facts", score_report),
            RubricJudgeEvaluator(REPORT_RUBRIC, reference_key="reference"),
        ]


def _backend(ctx: RunContext) -> SearchBackend:
    choice = ctx.params["backend"]
    if choice == "corpus":
        return CorpusSearch(corpus_documents())
    if not ctx.live or ctx.live_search is None:
        raise ValueError(f"backend {choice!r} needs --live and a runtime with live search")
    return ctx.live_search(choice)


def score_retrieval(ctx: EvalContext) -> list[Score]:
    tiers = {doc.id: doc.meta["tier"] for doc in corpus_documents()}
    fetched = [doc_id for doc_id in ctx.output.extras["fetched"] if doc_id in tiers]
    gold = set(ctx.task.data["gold_docs"])
    return [
        ratio_score(
            "preferred_source_ratio",
            sum(tiers[d] == "high" for d in fetched),
            len(fetched),
            "step",
            empty=0.0,
            threshold=0.5,
        ),
        ratio_score("gold_doc_recall", len(gold & set(fetched)), len(gold), "step"),
        ratio_score("low_quality_fetch_rate", sum(tiers[d] == "low" for d in fetched), len(fetched), "step", empty=0.0),
    ]


def fact_recall(text: str, facts: list[dict[str, Any]]) -> tuple[float, list[str]]:
    lowered = text.lower()
    missing = [fact["key"] for fact in facts if not any(pattern in lowered for pattern in fact["patterns"])]
    return (len(facts) - len(missing)) / len(facts), missing


def score_report(ctx: EvalContext) -> list[Score]:
    facts = ctx.task.data["facts"]
    recall, missing = fact_recall(ctx.output.final, facts)
    draft_recall, _ = fact_recall(ctx.output.extras["draft"], facts)
    repeated = [claim for claim in ctx.task.data["wrong_claims"] if claim in ctx.output.final.lower()]
    known = {doc.id for doc in corpus_documents()}
    cited = _CITATION.findall(ctx.output.final)
    valid = [c for c in cited if c in known and c in ctx.output.extras["fetched"]]
    return [
        Score(name="fact_recall", value=recall, level="e2e", passed=recall >= 0.75, rationale=f"missing {missing}"),
        Score(name="draft_fact_recall", value=draft_recall, level="step"),
        Score(
            name="no_misinformation",
            value=float(not repeated),
            level="e2e",
            passed=not repeated,
            rationale=f"repeated {repeated}" if repeated else "none",
        ),
        ratio_score(
            "citation_validity",
            len(valid),
            len(cited),
            "e2e",
            empty=0.0,
            threshold=0.9,
            rationale=f"{len(valid)}/{len(cited)} citations point to fetched documents",
        ),
    ]
