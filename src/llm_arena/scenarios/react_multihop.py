"""Scenario: multi-hop questions about a fictional world, solved with the ReAct text protocol.

`variant` compares ReAct (thought + action), Act-only and CoT-only on identical tasks — CoT-only
should fail on fictional facts, which checks that the benchmark actually requires the tools.
"""

from __future__ import annotations

from typing import Any, Literal

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.compare import last_number, normalize_answer, numbers_match, token_f1
from llm_arena.eval.trace_checks import StopReasonEvaluator, ToolHygieneEvaluator
from llm_arena.mocks.search import CorpusSearch, Document
from llm_arena.mocks.world import articles, multihop_tasks
from llm_arena.patterns.react import run_react
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.brief import Brief, TaskView, text
from llm_arena.scenarios.workflow import END, START, Workflow, edge, step, when
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.registry import Tool, ToolRegistry, tool


def encyclopedia_tools(search: CorpusSearch) -> list[Tool]:
    @tool
    async def search_articles(query: str) -> list[dict[str, Any]]:
        """Search the encyclopedia; returns titles and snippets of the best matching articles."""
        return [{"title": hit["title"], "snippet": hit["snippet"]} for hit in await search.search(query, max_results=3)]

    @tool
    async def read_article(title: str) -> str:
        """Return the full text of the article with this exact title."""
        return str((await search.fetch(title))["text"])

    return [search_articles, read_article]


@register
class ReactMultihop(Scenario):
    name = "react_multihop"
    title = "Multi-hop QA with ReAct"
    tokens_per_trial = 6000
    param_choices = {"variant": ["react", "act", "cot"]}
    pattern = "react"
    description = "Multi-hop QA over a fictional encyclopedia via Thought/Action/Observation."
    roles = [RoleRequirement("agent", "reasons and acts with text-protocol tools")]
    default_params = {"variant": "react", "max_steps": 10}
    pass_criteria = ["exact_match"]

    def load_tasks(self) -> list[Task]:
        return multihop_tasks()

    def fixtures(self) -> dict[str, Any]:
        corpus = CorpusSearch([Document(id=t, title=t, text=x) for t, x in articles().items()])
        return {"encyclopedia.json": articles(), "tools.json": [t.schema() for t in encyclopedia_tools(corpus)]}

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        corpus = CorpusSearch([Document(id=title, title=title, text=text) for title, text in articles().items()])
        executor = ToolExecutor(ToolRegistry(encyclopedia_tools(corpus)), ctx.trace, role="agent")
        variant: Literal["react", "act", "cot"] = ctx.params["variant"]
        result = await run_react(
            models["agent"],
            task.prompt,
            executor,
            ctx.trace,
            variant=variant,
            max_steps=ctx.params["max_steps"],
            extra_instructions="\nThe encyclopedia describes a fictional world: do not rely on outside knowledge.",
        )
        return TrialOutput(
            final=result.final,
            extras={
                "stop_reason": result.stop_reason,
                "steps": result.steps,
                "invalid_actions": result.invalid_actions,
            },
        )

    def brief(self) -> Brief:
        return Brief(
            summary="Multi-hop questions over a fictional encyclopedia: reason and act (ReAct) vs act only vs "
            "reason only.",
            environment="An encyclopedia of a fictional world, looked up with a plain-text Thought/Action protocol, "
            "so any chat model can play.",
            criteria={"exact_match": "the final answer matches"},
            measured=["premature_answer: answered with fewer lookups than hops", "invalid actions", "f1 of the answer"],
            traps=["the facts are fictional, so answering from memory fails"],
            compare=["variant: react vs act vs cot"],
        )  # fmt: skip

    def describe(self, task: Task) -> TaskView:
        return TaskView(id=task.id, prompt=task.prompt, tags=task.tags, expected=[
            text("Answer", task.data["answer"]), text("Lookups needed", task.data["hops"]),
        ])  # fmt: skip

    def workflow(self) -> Workflow:
        tools = when("variant", in_=["react", "act"])
        return Workflow(
            steps=[START,
                   step("think", "Thought → Action", "llm", "agent", "writes its reasoning, then an action",
                        when("variant", equals="react")),
                   step("act", "Action", "llm", "agent", "acts without written thoughts", when("variant", equals="act")),
                   step("cot", "Reason, then answer", "llm", "agent", "chain of thought, no tools",
                        when("variant", equals="cot")),
                   step("tools", "Encyclopedia lookup", "tool", when=tools), END],
            edges=[edge("start", "think"), edge("start", "act"), edge("start", "cot"),
                   edge("think", "tools", "action"), edge("act", "tools", "action"),
                   edge("tools", "think", "observation", loop=True), edge("tools", "act", "observation", loop=True),
                   edge("think", "end", "final answer"), edge("act", "end", "final answer"), edge("cot", "end")],
        )  # fmt: skip

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [ToolHygieneEvaluator(), StopReasonEvaluator(), FunctionEvaluator("react_answer", score_answer)]


def score_answer(ctx: EvalContext) -> list[Score]:
    gold = str(ctx.task.data["answer"])
    prediction = ctx.output.final
    if "numeric" in ctx.task.data:
        correct = numbers_match(last_number(prediction), float(ctx.task.data["numeric"]))
    else:
        correct = normalize_answer(gold) in normalize_answer(prediction)
    tool_calls = len(ctx.trace.select("tool_call"))
    hops = int(ctx.task.data["hops"])
    return [
        Score(name="exact_match", value=float(correct), level="e2e", passed=correct, rationale=f"gold={gold!r}"),
        Score(name="f1", value=token_f1(prediction, gold), level="e2e"),
        Score(name="steps", value=float(ctx.output.extras["steps"]), level="step"),
        Score(
            name="invalid_actions",
            value=float(ctx.output.extras["invalid_actions"]),
            level="step",
            passed=ctx.output.extras["invalid_actions"] == 0,
        ),
        # Answering in fewer lookups than the question has hops means guessing, even if lucky.
        Score(name="premature_answer", value=float(tool_calls < hops - 1), level="step", passed=tool_calls >= hops - 1),
    ]
