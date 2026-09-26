"""ArenaService: the one application API behind every front end.

The CLI, the local FastAPI app and the browser (Pyodide) worker all call these methods; inputs and
outputs are JSON-serialisable contracts, so the web UI talks to the local server over HTTP and to
the browser engine over postMessage with the same payloads. Everything environment-specific comes
in through the Runtime and a RunStore factory.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from llm_arena.llm.catalog import Catalog
from llm_arena.llm.pricing import known_price, price_per_mtok
from llm_arena.llm.spec import ModelSpec
from llm_arena.report.aggregate import ConfigSummary, PairedTest, summarize
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import EventSink, ignore
from llm_arena.runner.ports import RunStore, Runtime
from llm_arena.runner.run import ExperimentRunner, new_run_id
from llm_arena.scenarios.base import SCENARIOS, get_scenario
from llm_arena.scenarios.manifest import ScenarioManifest

JUDGE_TOKENS_PER_TRIAL = 1500  # rubric judging; a rough allowance for the estimate


class RuntimeInfo(BaseModel):
    runtime: str
    sandbox: bool
    live_search: bool
    providers: dict[str, str] = Field(description="provider -> 'available' or why not (never key material)")


class Estimate(BaseModel):
    trials: int
    per_scenario: dict[str, int]
    tokens: int
    cost_usd: float
    unknown_prices: list[str] = Field(default_factory=list, description="models without a known price (costed at 0)")
    note: str = "Rough estimate from typical tokens per trial; actual spend depends on model verbosity."


class BundleSummary(BaseModel):
    configs: list[ConfigSummary]
    paired_tests: list[PairedTest]
    ratings: dict[str, dict[str, float]] = Field(description="scope ('overall' or scenario) -> config -> rating")


class RunBundle(BaseModel):
    """Everything the report viewer needs for one run; export/import format between runtimes."""

    run: dict[str, Any]
    summary: BundleSummary
    trials: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    battles: list[dict[str, Any]]
    traces: dict[str, Any]


class ArenaService:
    def __init__(
        self,
        runtime: Runtime,
        *,
        store_factory: Callable[[str], RunStore],
        model_specs: dict[str, ModelSpec] | None = None,
    ) -> None:
        self.runtime = runtime
        self.store_factory = store_factory
        self.model_specs = model_specs or {}
        self._catalog: Catalog | None = None
        self._runners: dict[str, ExperimentRunner] = {}
        self._tasks: dict[str, asyncio.Task[str]] = {}

    # ---- discovery ------------------------------------------------------------------------
    def list_scenarios(self) -> list[ScenarioManifest]:
        get_scenario("email_assistant")  # importing registers every scenario
        return [get_scenario(name).manifest() for name in sorted(SCENARIOS)]

    async def catalog(self, *, refresh: bool = False) -> Catalog:
        if self._catalog is None or refresh:
            self._catalog = await self.runtime.discover() if self.runtime.discover else Catalog()
        return self._catalog

    async def runtime_info(self) -> RuntimeInfo:
        catalog = await self.catalog()
        providers: dict[str, str] = {entry.source: "available" for entry in catalog.entries}
        providers.update({source: reason for source, reason in catalog.errors.items() if source not in providers})
        return RuntimeInfo(
            runtime=self.runtime.name,
            sandbox=self.runtime.sandbox is not None,
            live_search=self.runtime.live_search is not None,
            providers=providers,
        )

    # ---- planning -------------------------------------------------------------------------
    async def estimate(self, experiment: ExperimentConfig) -> Estimate:
        runner = self._runner(experiment, run_id="estimate")
        await runner.prepare()
        trials = runner.plan()
        per_scenario: dict[str, int] = {}
        tokens = 0
        cost = 0.0
        unknown: set[str] = set()
        judge = runner.judge_spec
        for trial in trials:
            per_scenario[trial.scenario.name] = per_scenario.get(trial.scenario.name, 0) + 1
            models = list({spec.name: spec for spec in trial.bindings.values()}.values())
            share = trial.scenario.tokens_per_trial / len(models)
            for spec in models:
                cost += _cost(spec, share, unknown)
            tokens += trial.scenario.tokens_per_trial
            if judge is not None:
                cost += _cost(judge, JUDGE_TOKENS_PER_TRIAL, unknown)
                tokens += JUDGE_TOKENS_PER_TRIAL
        return Estimate(
            trials=len(trials), per_scenario=per_scenario, tokens=tokens, cost_usd=round(cost, 4),
            unknown_prices=sorted(unknown),
        )  # fmt: skip

    # ---- running --------------------------------------------------------------------------
    async def start_run(
        self, experiment: ExperimentConfig, *, sink: EventSink = ignore, run_id: str | None = None, live: bool = False
    ) -> str:
        """Start a run in the background and return its id; progress arrives through `sink`."""
        run_id = run_id or new_run_id(experiment.name)
        runner = self._runner(experiment, run_id=run_id, sink=sink, live=live)
        runner.store = self.store_factory(run_id)
        self._runners[run_id] = runner
        self._tasks[run_id] = asyncio.create_task(runner.run())
        return run_id

    async def wait(self, run_id: str) -> str:
        return await self._tasks[run_id]

    def cancel(self, run_id: str) -> None:
        if run_id in self._runners:
            self._runners[run_id].cancel()

    def run_bundle(self, run_id: str, *, max_traces: int = 400) -> RunBundle:
        store = self.store_factory(run_id)
        data = store.load_run()
        summary = summarize(data)
        traces = {trial["trial_id"]: store.load_trace(trial["trial_id"]) for trial in data.trials[:max_traces]}
        return RunBundle(
            run=data.run,
            summary=BundleSummary(configs=summary.configs, paired_tests=summary.paired_tests, ratings=summary.ratings),
            trials=data.trials,
            scores=data.scores,
            battles=data.battles,
            traces=traces,
        )

    def _runner(
        self, experiment: ExperimentConfig, *, run_id: str, sink: EventSink = ignore, live: bool = False
    ) -> ExperimentRunner:
        return ExperimentRunner(
            experiment,
            self.runtime,
            run_id=run_id,
            live=live,
            model_specs=self.model_specs,
            catalog=self._catalog,
            sink=sink,
        )


def _cost(spec: ModelSpec, tokens: float, unknown: set[str]) -> float:
    if (
        spec.provider in ("openai", "anthropic")
        and known_price(spec.model) is None
        and spec.input_cost_per_mtok is None
    ):
        unknown.add(spec.name)
    input_price, output_price = price_per_mtok(spec)
    return (tokens * 0.8 * input_price + tokens * 0.2 * output_price) / 1_000_000
