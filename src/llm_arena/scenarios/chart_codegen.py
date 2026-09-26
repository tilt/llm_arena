"""Scenario: chart generation — code execution plus reflection by a vision-capable critic.

generator writes matplotlib code → sandbox renders chart.png → critic *looks at the image*
(or only at the code, `critic_sees_image: false`, to measure what vision adds) → generator
revises. Charts are graded by code (introspected figure structure) and optionally a VLM judge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.judge import Criterion, Rubric, RubricJudgeEvaluator
from llm_arena.llm.client import system, user
from llm_arena.mocks.chart_data import (
    INTROSPECTION_PRELUDE,
    PRODUCTS,
    SITES,
    energy_csv,
    roastery_csv,
    weather_sales_csv,
)
from llm_arena.patterns.codeact import extract_code
from llm_arena.patterns.reflection import Critique, llm_critique, reflect
from llm_arena.patterns.roles import RoleModels
from llm_arena.sandbox.base import ExecResult
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register

DATASETS = {"energy.csv": energy_csv, "roastery.csv": roastery_csv, "weather_sales.csv": weather_sales_csv}

TASKS: list[dict[str, Any]] = [
    {
        "id": "energy_lines",
        "prompt": "Using energy.csv, draw a line chart of monthly energy output (kWh) in 2025 with one "
        "line per site, a title, labelled axes and a legend.",
        "data": {"file": "energy.csv", "expect": {"lines": 3, "legend": SITES}},
    },
    {
        "id": "quarterly_grouped_bars",
        "prompt": "Using roastery.csv, draw a grouped bar chart of total revenue per quarter "
        "of 2025 for each coffee product (quarters on the x-axis, one bar colour per product) with a title, labelled axes "
        "and a legend.",
        "data": {"file": "roastery.csv", "expect": {"bars": 16, "legend": PRODUCTS}},
    },
    {
        "id": "units_sorted_barh",
        "prompt": "Using roastery.csv, draw a horizontal bar chart of total units sold per "
        "product in 2025, sorted so the best seller is at the top. Add a title and axis labels.",
        "data": {"file": "roastery.csv", "expect": {"bars": 4, "horizontal_sorted": True}},
    },
    {
        "id": "temp_scatter_trend",
        "prompt": "Using weather_sales.csv, draw a scatter plot of cold brew cups sold against "
        "the daily maximum temperature, add a straight linear trend line, a title and labelled axes.",
        "data": {"file": "weather_sales.csv", "expect": {"scatter_points": 60, "min_lines": 1}},
    },
]

CHART_RUBRIC = Rubric(
    name="chart_quality",
    criteria=[
        Criterion(
            name="faithful", description="The chart shows exactly what the task asked for, with plausible values."
        ),
        Criterion(name="legible", description="Labels, ticks and legend are readable and do not overlap."),
        Criterion(name="informative", description="Title and axis labels explain what is shown, including units."),
    ],
)

_RULES = (
    "Write a complete Python script with pandas and matplotlib that reads the CSV from the current directory and saves "
    "the figure as chart.png (dpi=100). Do not call plt.show(). Return only one ```python block."
)


@register
class ChartCodegen(Scenario):
    name = "chart_codegen"
    title = "Chart code with a vision critic"
    tokens_per_trial = 6000
    requires = frozenset({"sandbox"})
    pattern = "code_execution+reflection"
    description = (
        "Matplotlib chart generation; a (vision) critic reviews the rendered chart; graded by figure introspection."
    )
    roles = [
        RoleRequirement("generator", "writes and revises plotting code"),
        RoleRequirement("critic", "reviews the rendered chart image", needs=frozenset({"vision"})),
    ]
    default_params = {"reflection_rounds": 1, "critic_sees_image": True, "timeout_s": 60}
    pass_criteria = ["chart_rendered", "spec_compliance"]
    open_ended = True
    pairwise_criteria = "Which chart better fulfils the request: correct data encoding, legibility, labelling."

    def load_tasks(self) -> list[Task]:
        return [Task.model_validate(entry) for entry in TASKS]

    def fixtures(self) -> dict[str, Any]:
        files: dict[str, Any] = {name: make() for name, make in DATASETS.items()}
        files["introspection_prelude.py"] = INTROSPECTION_PRELUDE.lstrip()
        files["rubrics.json"] = [CHART_RUBRIC.model_dump()]
        return files

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        sandbox = ctx.require_sandbox()
        filename = task.data["file"]
        csv_text = DATASETS[filename]()
        head = "\n".join(csv_text.splitlines()[:6])
        attempts: list[ExecResult] = []
        codes: list[str] = []
        generator, critic = models["generator"], models["critic"]

        async def render(code: str) -> str:
            with ctx.trace.span("code_exec", "render_chart", input=code) as span:
                result = await sandbox.run(
                    INTROSPECTION_PRELUDE,
                    files={"user_code.py": code, filename: csv_text},
                    collect=("chart.png", "figure_spec.json"),
                    timeout_s=ctx.params["timeout_s"],
                )
                span.output = result.observation()
                span.attrs.update({"ok": result.ok, "png": "chart.png" in result.files})
            attempts.append(result)
            codes.append(code)
            return code

        async def draft() -> str:
            prompt = f"Task: {task.prompt}\n\nFile {filename} (first rows):\n{head}"
            return await render(extract_code((await generator.complete([system(_RULES), user(prompt)])).content) or "")

        async def critique(code: str, _round: int) -> Critique:
            latest = attempts[-1]
            png = latest.files.get("chart.png")
            evidence = f"Execution: {latest.observation()}"
            images: list[str | Path | bytes] = [png] if png and ctx.params["critic_sees_image"] else []
            return await llm_critique(
                critic,
                [
                    system(
                        "You review charts. Check the chart answers the request, encodes the data correctly and is "
                        "clearly labelled. Accept only if nothing needs to change."
                    ),
                    user(f"Request: {task.prompt}\n\nCode:\n```python\n{code}\n```\n{evidence}", images),
                ],
            )

        async def revise(code: str, review: Critique, _round: int) -> str:
            issues = "\n- ".join(review.issues or [review.summary])
            prompt = (
                f"Task: {task.prompt}\n\nFile {filename} (first rows):\n{head}\n\nCurrent code:\n```python\n{code}\n```\n"
                f"Execution: {attempts[-1].observation()}\n\nReviewer feedback:\n- {issues}\n\nReturn the improved script."
            )
            return await render(extract_code((await generator.complete([system(_RULES), user(prompt)])).content) or "")

        await reflect(
            draft=draft, critique=critique, revise=revise, rounds=ctx.params["reflection_rounds"], trace=ctx.trace
        )
        final = attempts[-1]
        artifacts = {"chart.png": final.files["chart.png"]} if "chart.png" in final.files else {}
        return TrialOutput(
            final=codes[-1],
            artifacts=artifacts,
            extras={"specs": [_spec(a) for a in attempts], "ok": [a.ok for a in attempts]},
        )

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [
            FunctionEvaluator("chart_spec", score_chart),
            VisionJudge(RubricJudgeEvaluator(CHART_RUBRIC, include_artifacts=True)),
        ]


def _spec(result: ExecResult) -> dict[str, Any] | None:
    raw = result.files.get("figure_spec.json")
    return json.loads(raw) if raw else None


def check_spec(spec: dict[str, Any] | None, expect: dict[str, Any]) -> list[str]:
    """Return the list of failed checks (empty = compliant)."""
    if not spec or not spec["axes"]:
        return ["no figure saved"]
    axis = spec["axes"][0]
    failures = []
    if not (axis["title"] or spec["suptitle"]):
        failures.append("missing title")
    if not axis["xlabel"] or not axis["ylabel"]:
        failures.append("missing axis label")
    if "lines" in expect and axis["lines"] != expect["lines"]:
        failures.append(f"{axis['lines']} lines, expected {expect['lines']}")
    if "min_lines" in expect and axis["lines"] < expect["min_lines"]:
        failures.append("missing trend line")
    if "bars" in expect and len(axis["bars"]) != expect["bars"]:
        failures.append(f"{len(axis['bars'])} bars, expected {expect['bars']}")
    if "scatter_points" in expect and axis["scatter_points"] != expect["scatter_points"]:
        failures.append(f"{axis['scatter_points']} scatter points, expected {expect['scatter_points']}")
    if "legend" in expect:
        legend = " ".join(axis["legend"] + spec["figure_legend"]).lower()
        missing = [name for name in expect["legend"] if name.lower() not in legend]
        if missing:
            failures.append(f"legend lacks {missing}")
    if expect.get("horizontal_sorted") and not _sorted_top_down(axis):
        failures.append("bars not horizontal or not sorted with the largest at the top")
    return failures


def _sorted_top_down(axis: dict[str, Any]) -> bool:
    bars = axis["bars"]  # [x, y, width, height]
    if not bars or any(orientation != "horizontal" for orientation in axis["bar_orientation"]):
        return False
    ordered = sorted(bars, key=lambda bar: bar[1], reverse=not axis["y_inverted"])  # top of the chart first
    widths = [bar[2] for bar in ordered]
    return widths == sorted(widths, reverse=True)


def score_chart(ctx: EvalContext) -> list[Score]:
    expect = ctx.task.data["expect"]
    specs, ok = ctx.output.extras["specs"], ctx.output.extras["ok"]
    draft_failures, final_failures = check_spec(specs[0], expect), check_spec(specs[-1], expect)
    rendered = ok[-1] and "chart.png" in ctx.output.artifacts
    return [
        Score(name="draft_executes", value=float(ok[0]), level="step", passed=ok[0]),
        Score(
            name="draft_spec_compliance",
            value=float(not draft_failures),
            level="step",
            passed=not draft_failures,
            rationale="; ".join(draft_failures),
        ),
        Score(name="chart_rendered", value=float(rendered), level="e2e", passed=rendered),
        Score(
            name="spec_compliance",
            value=float(not final_failures),
            level="e2e",
            passed=not final_failures,
            rationale="; ".join(final_failures) or "all checks passed",
        ),
    ]


class VisionJudge:
    """Runs the wrapped judge only when the judge model can see images."""

    def __init__(self, inner: RubricJudgeEvaluator) -> None:
        self.inner = inner
        self.name = inner.name

    async def evaluate(self, ctx: EvalContext) -> list[Score]:
        if ctx.judge is None or not ctx.judge.spec.capabilities.vision or not ctx.output.artifacts:
            return []
        return await self.inner.evaluate(ctx)
