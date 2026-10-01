"""ArenaService: the one application API behind every front end.

The CLI, the local FastAPI app and the browser (Pyodide) worker all call these methods; inputs and
outputs are JSON-serialisable contracts, so the web UI talks to the local server over HTTP and to
the browser engine over postMessage with the same payloads. Everything environment-specific comes
in through the Runtime and a RunStore factory.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from llm_arena.core.errors import ConfigError
from llm_arena.decisions.config import SERVICES
from llm_arena.decisions.records import DecisionSummary
from llm_arena.llm.catalog import Catalog
from llm_arena.llm.pricing import known_price, price_per_mtok
from llm_arena.llm.spec import ModelSpec
from llm_arena.report.aggregate import ConfigSummary, PairedTest, ReplacementEffect, summarize
from llm_arena.report.leaderboard import Leaderboard, build_leaderboards
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import EventSink, ignore
from llm_arena.runner.ports import RunData, RunStore, Runtime
from llm_arena.runner.presets import DEFAULT_PRESETS, ModelPreset, save_preset
from llm_arena.runner.rename import RenameRun, rename_data, rename_trace
from llm_arena.runner.run import ExperimentRunner, new_run_id, valid_run_id
from llm_arena.scenarios.base import SCENARIOS, get_scenario
from llm_arena.scenarios.brief import TaskView
from llm_arena.scenarios.manifest import ScenarioManifest

JUDGE_TOKENS_PER_TRIAL = 1500  # rubric judging; a rough allowance for the estimate


class DecisionServiceInfo(BaseModel):
    status: str = Field(description="'available' or why not")
    models: list[str] = Field(default_factory=list)


class RuntimeInfo(BaseModel):
    runtime: str
    sandbox: bool
    sandbox_isolation: str = Field(default="", description="container | process | browser worker ('' without one)")
    sandbox_daemon: str = Field(
        default="",
        description="Docker only: 'rootless', 'root' (the daemon runs as root) or 'vm' (e.g. Docker Desktop)",
    )
    sandbox_hint: str = Field(default="", description="actionable setup help when code execution is unavailable")
    live_search: bool
    providers: dict[str, str] = Field(description="provider -> 'available' or why not (never key material)")
    decision_services: dict[str, DecisionServiceInfo] = Field(
        default_factory=dict, description="'jev' / 'ollaya' -> availability and models (System One decision models)"
    )


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
    decisions: list[DecisionSummary] = Field(default_factory=list, description="control-policy decision quality")
    replacements: list[ReplacementEffect] = Field(
        default_factory=list, description="replacement studies: each swapped step against the baseline"
    )


class BundledArtifact(BaseModel):
    media_type: str
    data: str = Field(description="base64")


class RunBundle(BaseModel):
    """Everything the report viewer needs for one run; export/import format between runtimes."""

    run: dict[str, Any]
    summary: BundleSummary
    trials: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    battles: list[dict[str, Any]]
    decisions: list[dict[str, Any]] = Field(default_factory=list, description="one row per control decision × question")
    traces: dict[str, Any] = Field(default_factory=dict, description="trial id -> trace (empty when loaded lazily)")
    artifacts: dict[str, BundledArtifact] = Field(
        default_factory=dict, description="artifact key -> file, for the included traces (exports, browser storage)"
    )


class ArenaService:
    def __init__(
        self,
        runtime: Runtime,
        *,
        store_factory: Callable[[str], RunStore],
        model_specs: dict[str, ModelSpec] | None = None,
        presets: dict[str, ModelPreset] | None = None,
        presets_file: Path | None = None,
    ) -> None:
        """`presets_file`: where edited profiles are saved (local app); None: profiles are read-only here."""
        self.runtime = runtime
        self.store_factory = store_factory
        self.model_specs = model_specs or {}
        self.presets = dict(presets or DEFAULT_PRESETS)
        self.presets_file = presets_file
        self._catalog: Catalog | None = None
        self._runners: dict[str, ExperimentRunner] = {}
        self._tasks: dict[str, asyncio.Task[str]] = {}

    # ---- discovery ------------------------------------------------------------------------
    def list_scenarios(self) -> list[ScenarioManifest]:
        get_scenario("email_assistant")  # importing registers every scenario
        return [get_scenario(name).manifest() for name in sorted(SCENARIOS)]

    def tasks(self, scenario: str) -> list[TaskView]:
        """A scenario's tasks with their expected outcomes (benchmarks download their pinned subset on first use)."""
        found = get_scenario(scenario)
        return [found.describe(task) for task in found.load_tasks()]

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
            sandbox_isolation=getattr(self.runtime.sandbox, "isolation", "") if self.runtime.sandbox else "",
            sandbox_daemon=getattr(self.runtime.sandbox, "daemon", "") if self.runtime.sandbox else "",
            sandbox_hint=self.runtime.sandbox_hint,
            live_search=self.runtime.live_search is not None,
            providers=providers,
            decision_services=await self._decision_services(),
        )

    async def _decision_services(self) -> dict[str, DecisionServiceInfo]:
        if self.runtime.decision_status is None:
            reason = "not available in the browser; use the local app or CLI"
            return {service: DecisionServiceInfo(status=reason) for service in SERVICES}
        return {name: DecisionServiceInfo(status=status, models=models)
                for name, (status, models) in (await self.runtime.decision_status()).items()}  # fmt: skip

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
        if not valid_run_id(run_id):
            raise ConfigError(
                "run ids must start with a letter or digit and use at most 121 letters, digits, ., _ or -"
            )
        runner = self._runner(experiment, run_id=run_id, sink=sink, live=live)
        await runner.preflight()  # configuration errors go to the caller, not into a background task
        runner.store = self.store_factory(run_id)
        self._runners[run_id] = runner
        self._tasks[run_id] = asyncio.create_task(runner.run())
        return run_id

    async def wait(self, run_id: str) -> str:
        return await self._tasks[run_id]

    def cancel(self, run_id: str) -> None:
        if run_id in self._runners:
            self._runners[run_id].cancel()

    def leaderboards(self, run_ids: list[str], *, scenario: str | None = None) -> list[Leaderboard]:
        """Pool the trials of the given runs into per-scenario leaderboards (unreadable runs are skipped)."""
        trials: list[dict[str, Any]] = []
        for run_id in run_ids:
            try:
                rows = self.store_factory(run_id).load_run().trials
            except Exception:  # a run being written by another process, or a damaged run directory
                continue
            trials += [{**row, "run_id": row.get("run_id") or run_id} for row in rows]
        return build_leaderboards(trials, scenario)

    def run_bundle(
        self,
        run_id: str,
        *,
        max_traces: int = 400,
        traces: bool = True,
        artifacts: bool = False,
        max_artifact_bytes: int = 50 * 1024 * 1024,
    ) -> RunBundle:
        """`traces=False` for a light bundle (the UI then loads traces per trial); `artifacts=True` embeds the
        files the included traces reference, up to `max_artifact_bytes` (exports, browser storage)."""
        store = self.store_factory(run_id)
        data = store.load_run()
        trial_traces = (
            {trial["trial_id"]: store.load_trace(trial["trial_id"]) for trial in data.trials[:max_traces]}
            if traces
            else {}
        )
        files: dict[str, BundledArtifact] = {}
        budget = max_artifact_bytes
        for key in _artifact_keys(trial_traces.values()) if artifacts else []:
            loaded = store.load_artifact(key)
            if loaded is None or len(loaded[0]) > budget:
                continue
            budget -= len(loaded[0])
            files[key] = BundledArtifact(media_type=loaded[1], data=base64.b64encode(loaded[0]).decode("ascii"))
        return RunBundle(
            run=data.run,
            summary=bundle_summary(data),
            trials=data.trials,
            scores=data.scores,
            battles=data.battles,
            decisions=data.decisions,
            traces=trial_traces,
            artifacts=files,
        )

    def rename_run(self, run_id: str, request: RenameRun) -> None:
        """New display name and setup names for a finished run (ids, links and results stay)."""
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            raise ConfigError("this run is still going: rename it once it has finished")
        self.store_factory(run_id).rename(request)

    def trial_trace(self, run_id: str, trial_id: str) -> dict[str, Any] | None:
        return self.store_factory(run_id).load_trace(trial_id)

    def artifact(self, run_id: str, key: str) -> tuple[bytes, str] | None:
        return self.store_factory(run_id).load_artifact(key)

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
            presets=self.presets,
        )

    def save_preset(self, name: str, profile: ModelPreset | None) -> dict[str, ModelPreset]:
        """Create, change or (None) reset a profile; persisted in the local override file."""
        if self.presets_file is None:
            raise ConfigError("presets cannot be saved in this runtime")
        save_preset(self.presets_file, name, profile)
        if profile is not None:
            self.presets[name] = profile
        elif name in DEFAULT_PRESETS:
            self.presets[name] = DEFAULT_PRESETS[name]
        else:
            self.presets.pop(name, None)
        return self.presets


def bundle_summary(data: RunData) -> BundleSummary:
    summary = summarize(data)
    return BundleSummary(
        configs=summary.configs,
        paired_tests=summary.paired_tests,
        ratings=summary.ratings,
        decisions=summary.decisions,
        replacements=summary.replacements,
    )


def rename_bundle(bundle: RunBundle, request: RenameRun) -> RunBundle:
    """A saved bundle (browser storage, imports) with new names; its summary is recomputed from the renamed rows."""
    rows = RunData(run=bundle.run, trials=bundle.trials, scores=bundle.scores, battles=bundle.battles,
                   decisions=bundle.decisions)  # fmt: skip
    data, renames = rename_data(rows, request)
    return bundle.model_copy(update={
        "run": data.run, "summary": bundle_summary(data), "trials": data.trials, "battles": data.battles,
        "decisions": data.decisions,
        "traces": {trial_id: rename_trace(trace, renames) for trial_id, trace in bundle.traces.items()},
    })  # fmt: skip


def _cost(spec: ModelSpec, tokens: float, unknown: set[str]) -> float:
    if (
        spec.provider in ("openai", "anthropic")
        and known_price(spec.model) is None
        and spec.input_cost_per_mtok is None
    ):
        unknown.add(spec.name)
    input_price, output_price = price_per_mtok(spec)
    return (tokens * 0.8 * input_price + tokens * 0.2 * output_price) / 1_000_000


def _artifact_keys(traces: Iterable[dict[str, Any] | None]) -> list[str]:
    return [
        ref["key"]
        for trace in traces
        if trace
        for span in trace.get("spans", [])
        for ref in span.get("artifacts", [])
        if ref.get("key")
    ]
