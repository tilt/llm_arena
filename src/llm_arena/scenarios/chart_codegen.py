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
from llm_arena.eval.credit import share
from llm_arena.eval.judge import Criterion, Rubric, RubricJudgeEvaluator
from llm_arena.llm.client import system, user
from llm_arena.mocks.chart_data import (
    INTROSPECTION_PRELUDE,
    PRODUCTS,
    SITES,
    energy_csv,
    expected_data,
    roastery_csv,
    weather_sales_csv,
)
from llm_arena.patterns.codeact import extract_code
from llm_arena.patterns.reflection import Critique, llm_critique, reflect
from llm_arena.patterns.roles import RoleModels
from llm_arena.sandbox.base import ExecResult
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.brief import Brief, TaskView, as_json, text
from llm_arena.scenarios.workflow import Workflow, reflection, step

DATASETS = {"energy.csv": energy_csv, "roastery.csv": roastery_csv, "weather_sales.csv": weather_sales_csv}

TASKS: list[dict[str, Any]] = [
    {
        "id": "energy_lines",
        "prompt": "Using energy.csv, draw a line chart of monthly energy output (kWh) in 2025 with one "
        "line per site, a title, labelled axes and a legend.",
        "data": {"file": "energy.csv", "expect": {"lines": 3, "legend": SITES, "data": "monthly_kwh_per_site"}},
    },
    {
        "id": "quarterly_grouped_bars",
        "prompt": "Using roastery.csv, draw a grouped bar chart of total revenue per quarter "
        "of 2025 for each coffee product (quarters on the x-axis, one bar colour per product) with a title, labelled axes "
        "and a legend.",
        "data": {
            "file": "roastery.csv",
            "expect": {"bars": 16, "legend": PRODUCTS, "data": "quarterly_revenue_per_product"},
        },
    },
    {
        "id": "units_sorted_barh",
        "prompt": "Using roastery.csv, draw a horizontal bar chart of total units sold per "
        "product in 2025, sorted so the best seller is at the top. Add a title and axis labels.",
        "data": {"file": "roastery.csv", "expect": {"bars": 4, "horizontal_sorted": True, "data": "units_per_product"}},
    },
    {
        "id": "temp_scatter_trend",
        "prompt": "Using weather_sales.csv, draw a scatter plot of cold brew cups sold against "
        "the daily maximum temperature, add a straight linear trend line, a title and labelled axes.",
        "data": {
            "file": "weather_sales.csv",
            "expect": {"scatter_points": 60, "min_lines": 1, "data": "temperature_vs_cups"},
        },
    },
]

DATA_CHECKS = {  # what the data check verifies, per task (see mocks.chart_data.expected_data)
    "monthly_kwh_per_site": "each site's line has its 12 monthly kWh values from energy.csv",
    "quarterly_revenue_per_product": "the 16 bars are the quarterly revenue totals per product from roastery.csv",
    "units_per_product": "the 4 bars are the total units per product from roastery.csv",
    "temperature_vs_cups": "the 60 points are the rows of weather_sales.csv, temperature on x and cups on y",
}

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
    # 2: plotted data is checked point by point; the critic separates data from presentation.
    # 3: spec_compliance scores the share of spec checks met (partial credit).
    version = "3"
    regrades_from = frozenset({"2"})  # only grading changed since
    title = "Chart code with a vision critic"
    tokens_per_trial = 6000
    requires = frozenset({"sandbox"})
    pattern = "code_execution+reflection"
    description = (
        "Matplotlib chart generation; a (vision) critic reviews the rendered chart; graded by figure introspection."
    )
    roles = [
        RoleRequirement("generator", "writes and revises plotting code", kind="code"),
        RoleRequirement("critic", "reviews the rendered chart image", needs=frozenset({"vision"}), kind="vision"),
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
            with ctx.trace.in_step("render"), ctx.trace.span("code_exec", "render_chart", input=code) as span:
                result = await sandbox.run(
                    INTROSPECTION_PRELUDE,
                    files={"user_code.py": code, filename: csv_text},
                    collect=("chart.png", "figure_spec.json"),
                    timeout_s=ctx.params["timeout_s"],
                )
                span.output = result.observation()
                span.attrs.update(
                    {
                        "ok": result.ok,
                        "png": "chart.png" in result.files,
                        "output_truncated": result.output_truncated,
                        "omitted": result.omitted,
                    }
                )
                for name, media in (("chart.png", "image/png"), ("figure_spec.json", "application/json")):
                    if name in result.files:
                        ctx.trace.attach(span, name, result.files[name], media)
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
                        "clearly labelled. Judge what is plotted (series, points, values) separately from how it is "
                        "presented (title, labels, ticks, legend), and name each problem concretely. Accept only if "
                        "nothing needs to change."
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

        outcome = await reflect(
            draft=draft, critique=critique, revise=revise, rounds=ctx.params["reflection_rounds"], trace=ctx.trace
        )
        final = attempts[-1]
        artifacts = {"chart.png": final.files["chart.png"]} if "chart.png" in final.files else {}
        return TrialOutput(
            final=codes[-1],
            artifacts=artifacts,
            extras={
                "specs": [_spec(a) for a in attempts],
                "ok": [a.ok for a in attempts],
                "errors": [None if a.ok else _last_error(a) for a in attempts],
                "verdicts": [c.verdict for c in outcome.critiques],
            },
        )

    def brief(self) -> Brief:
        return Brief(
            summary="Code generation with a vision critic: the model writes matplotlib code, the chart is rendered, "
            "and a critic that sees the image asks for fixes.",
            environment="Synthetic CSV files and a Python sandbox; a prelude records the figure's structure (lines, "
            "bars, labels, legend) so the chart can be checked by code.",
            criteria={"chart_rendered": "the code ran and produced chart.png",
                      "spec_compliance": "the figure matches the request and plots every data point with its value "
                      "from the CSV: series count, data, labels, legend entries, "
                      "sorted bars where asked"},
            measured=["how many renders failed", "whether the critic's image review led to a better chart"],
            compare=["critic_sees_image: true vs false (what does vision add?)", "reflection_rounds: 0 vs 1"],
        )  # fmt: skip

    def describe(self, task: Task) -> TaskView:
        expect = {k: v for k, v in task.data["expect"].items() if k != "data"}
        return TaskView(id=task.id, prompt=task.prompt, tags=task.tags, expected=[
            text("Data file", task.data["file"]), as_json("The figure must have", expect),
            text("Every data point", DATA_CHECKS[task.data["expect"]["data"]]),
        ])  # fmt: skip

    def workflow(self) -> Workflow:
        render = step("render", "Render the chart", "code", description="sandbox; the figure is introspected")
        return reflection(generator="generator", critic="critic", draft="Write plotting code",
                          critique="Critic looks at the chart", revise="Fix the code", execute=render,
                          evidence="image + execution log")  # fmt: skip

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [
            FunctionEvaluator("chart_spec", score_chart),
            VisionJudge(RubricJudgeEvaluator(CHART_RUBRIC, include_artifacts=True)),
        ]


def _last_error(result: ExecResult) -> str:
    """The line that says what went wrong (the last line of the traceback), for rationales."""
    if result.timed_out:
        return "the code timed out"
    lines = [line.strip() for line in result.stderr.strip().splitlines() if line.strip()]
    return lines[-1] if lines else f"exit code {result.returncode}"


def _spec(result: ExecResult) -> dict[str, Any] | None:
    raw = result.files.get("figure_spec.json")
    return json.loads(raw) if raw else None


def check_spec(spec: dict[str, Any] | None, expect: dict[str, Any]) -> list[str]:
    """Return the list of failed checks (empty = compliant)."""
    return [problem for problem in spec_checks(spec, expect).values() if problem]


def spec_checks(spec: dict[str, Any] | None, expect: dict[str, Any]) -> dict[str, str | None]:
    """Each spec check that applies to the task, keyed: None when met, else the problem."""
    if not spec or not spec["axes"]:
        return {"figure": "no figure saved"}
    axis = spec["axes"][0]
    checks: dict[str, str | None] = {
        "title": None if axis["title"] or spec["suptitle"] else "missing title",
        "axis_labels": None if axis["xlabel"] and axis["ylabel"] else "missing axis label",
    }
    if "lines" in expect:
        checks["lines"] = (
            None if axis["lines"] == expect["lines"] else f"{axis['lines']} lines, expected {expect['lines']}"
        )
    if "min_lines" in expect:
        checks["min_lines"] = None if axis["lines"] >= expect["min_lines"] else "missing trend line"
    if "bars" in expect:
        checks["bars"] = (
            None if len(axis["bars"]) == expect["bars"] else f"{len(axis['bars'])} bars, expected {expect['bars']}"
        )
    if "scatter_points" in expect:
        checks["scatter_points"] = (
            None if axis["scatter_points"] == expect["scatter_points"]
            else f"{axis['scatter_points']} scatter points, expected {expect['scatter_points']}"
        )  # fmt: skip
    if "legend" in expect:
        legend = " ".join(axis["legend"] + spec["figure_legend"]).lower()
        missing = [name for name in expect["legend"] if name.lower() not in legend]
        checks["legend"] = f"legend lacks {missing}" if missing else None
    if expect.get("horizontal_sorted"):
        checks["horizontal_sorted"] = (
            None if _sorted_top_down(axis) else "bars not horizontal or not sorted with the largest at the top"
        )
    if check := expect.get("data"):
        checks.update(data_checks(axis, expected_data(check)))
    return checks


def _same_values(got: list[float], want: list[float]) -> bool:
    """Equal as multisets within rounding (plot order does not matter; units and aggregation do)."""
    return len(got) == len(want) and all(
        abs(g - w) <= max(0.5, 0.005 * abs(w)) for g, w in zip(sorted(got), sorted(want), strict=True)
    )


def check_data(axis: dict[str, Any], want: dict[str, Any]) -> list[str]:
    """Every data point present with the right value, per series (lines), per bar, or per scatter point."""
    return [problem for problem in data_checks(axis, want).values() if problem]


def data_checks(axis: dict[str, Any], want: dict[str, Any]) -> dict[str, str | None]:
    """One check per expected line series, for the bar values and for the scatter points."""
    checks: dict[str, str | None] = {}
    for series, values in want.get("line_values", {}).items():
        lines = axis.get("line_data", [])
        named = [line for line in lines if line["label"] == series]
        checks[f"data:{series}"] = None
        if not any(_same_values(line["y"], values) for line in named or lines):
            found = max((len(line["y"]) for line in named), default=None)
            detail = f"{found} points" if found is not None else "no line labelled so"
            checks[f"data:{series}"] = (
                f"{series}: expected its {len(values)} data points from the CSV ({detail} or other values)"
            )
    if "bar_values" in want:
        checks["data:bars"] = (
            None if _same_values(axis.get("bar_values", []), want["bar_values"])
            else f"bar values do not match the {len(want['bar_values'])} totals computed from the CSV"
        )  # fmt: skip
    if "scatter_points" in want:
        got = sorted((round(x, 1), round(y)) for x, y in axis.get("scatter_offsets", []))
        expected = sorted((round(x, 1), round(y)) for x, y in want["scatter_points"])
        checks["data:scatter"] = (
            None if got == expected
            else f"scatter points do not match the {len(expected)} rows of the CSV (temperature on x, cups on y)"
        )  # fmt: skip
    return checks


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
    final_share = share({key: problem is None for key, problem in spec_checks(specs[-1], expect).items()})
    rendered = ok[-1] and "chart.png" in ctx.output.artifacts
    errors = ctx.output.extras.get("errors") or [None] * len(ok)
    if rendered:
        why = "the final code rendered chart.png"
    elif not ok[-1]:
        why = f"the final code failed: {errors[-1] or 'error'}"
    else:
        why = "the final code ran but saved no chart.png"
    if len(ok) > 1 and not rendered and ok[0]:
        why += " (the draft had rendered: a revision broke it)"
    draft_ok, final_ok = not draft_failures, not final_failures
    critic: list[Score] = []
    if verdicts := ctx.output.extras.get("verdicts"):
        flagged = verdicts[0] == "revise"
        # Same reviewer indicators as reflection_sql: the report turns their means into precision/recall.
        critic = [
            Score(name="critic_tp", value=float(flagged and not draft_ok), level="step"),
            Score(name="critic_fp", value=float(flagged and draft_ok), level="step",
                  rationale="asked for changes to a draft that already met the spec" if flagged and draft_ok else ""),
            Score(name="critic_fn", value=float(not flagged and not draft_ok), level="step"),
            Score(name="critic_verdict_correct", value=float(flagged != draft_ok), level="step", passed=flagged != draft_ok),
        ]  # fmt: skip
    regressed = draft_ok and not final_ok
    return [
        *critic,
        Score(name="draft_executes", value=float(ok[0]), level="step", passed=ok[0]),
        Score(
            name="draft_spec_compliance",
            value=float(not draft_failures),
            level="step",
            passed=not draft_failures,
            rationale="; ".join(draft_failures),
        ),
        Score(name="chart_rendered", value=float(rendered), level="e2e", passed=rendered, rationale=why),
        Score(
            name="regressed",
            value=float(regressed),
            level="e2e",
            passed=not regressed,
            rationale="the draft met the spec, the final chart does not" if regressed else "",
        ),  # fmt: skip
        Score(
            name="spec_compliance",
            value=1.0 if not final_failures else final_share,
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

    def owns(self, score_name: str) -> bool:
        return self.inner.owns(score_name)

    async def evaluate(self, ctx: EvalContext) -> list[Score]:
        if ctx.judge is None or not ctx.judge.spec.capabilities.vision or not ctx.output.artifacts:
            return []
        return await self.inner.evaluate(ctx)
