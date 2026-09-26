"""Expand an experiment into trials, execute them concurrently, evaluate, persist, and run arena battles.

Pure orchestration: storage, model clients, discovery, sandbox and live search come in through
ports (`runner.ports`), progress goes out as events (`runner.events`). The same runner therefore
drives the CLI, the local app and the browser engine.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import json
import time
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from llm_arena.core.errors import ConfigError
from llm_arena.core.trace import Trace
from llm_arena.eval.base import EvalContext, Score, Task, TrialOutput
from llm_arena.eval.judge import judge_pairwise
from llm_arena.llm.cache import cache_salt
from llm_arena.llm.catalog import Catalog
from llm_arena.llm.client import LLMClient
from llm_arena.llm.registry import resolve_base_url, resolve_concurrency, resolve_model
from llm_arena.llm.spec import ModelSpec
from llm_arena.patterns.roles import RoleModels, TracedLLM
from llm_arena.runner.budget import BudgetExceededError, BudgetGuard
from llm_arena.runner.config import ExperimentConfig, PipelineConfig
from llm_arena.runner.events import (
    BudgetExceeded,
    EventSink,
    RunFinished,
    RunStarted,
    TrialFinished,
    TrialStarted,
    ignore,
)
from llm_arena.runner.ports import RunStore, Runtime, TrialRecord
from llm_arena.scenarios.base import RunContext, Scenario, get_scenario

WILDCARD_ROLE = "*"  # binds every role of a scenario that the config does not bind explicitly


@dataclass
class TrialSpec:
    scenario: Scenario
    config: PipelineConfig
    task: Task
    repeat: int
    bindings: dict[str, ModelSpec]
    params: dict[str, Any]

    @property
    def trial_id(self) -> str:
        key = f"{self.scenario.name}|{self.config.name}|{self.task.id}|{self.repeat}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]


def new_run_id(name: str) -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{name}"


class ExperimentRunner:
    def __init__(
        self,
        experiment: ExperimentConfig,
        runtime: Runtime,
        *,
        store: RunStore | None = None,
        run_id: str | None = None,
        live: bool = False,
        model_specs: dict[str, ModelSpec] | None = None,
        catalog: Catalog | None = None,
        sink: EventSink = ignore,
    ) -> None:
        self.experiment = experiment
        self.runtime = runtime
        self.store = store
        self.run_id = run_id or new_run_id(experiment.name)
        self.live = live
        self.model_specs = model_specs or {}
        self.catalog = catalog
        self.sink = sink
        self.budget = BudgetGuard(experiment.max_cost_usd)
        self._clients: dict[str, LLMClient] = {}
        self._cancelled = False
        self._planned: list[TrialSpec] | None = None

    def cancel(self) -> None:
        """Stop starting new trials; running trials finish."""
        self._cancelled = True

    @property
    def judge_spec(self) -> ModelSpec | None:
        return self._spec(self.experiment.judge) if self.experiment.judge else None

    def unresolved_refs(self) -> set[str]:
        """References that are not curated aliases, i.e. need discovery to get real capabilities."""
        refs = {ref for config in self.experiment.configs for ref in config.roles.values()}
        refs |= {ref for ref in (self.experiment.judge, self.experiment.arena.judge) if ref}
        return {ref for ref in refs if ref not in self.model_specs}

    async def prepare(self) -> None:
        """Discover installed models once, if any reference needs it."""
        if self.catalog is None and self.unresolved_refs() and self.runtime.discover is not None:
            self.catalog = await self.runtime.discover()

    # ---- planning -------------------------------------------------------------------------
    def plan(self) -> list[TrialSpec]:
        trials: list[TrialSpec] = []
        for scenario_name in self.experiment.scenarios:
            scenario = get_scenario(scenario_name)
            tasks = self._select_tasks(scenario.load_tasks())
            for config in self.experiment.configs:
                if config.scenarios is not None and scenario_name not in config.scenarios:
                    continue
                bindings = scenario.check_roles(self._bind(scenario, config))
                params = scenario.params(config.params_for(scenario_name, set(scenario.default_params)))
                trials += [
                    TrialSpec(scenario, config, task, repeat, bindings, params)
                    for task in tasks
                    for repeat in range(self.experiment.repeats)
                ]
        return trials

    def _select_tasks(self, tasks: list[Task]) -> list[Task]:
        if self.experiment.task_ids:
            tasks = [task for task in tasks if task.id in set(self.experiment.task_ids)]
        return tasks[: self.experiment.limit] if self.experiment.limit else tasks

    def _bind(self, scenario: Scenario, config: PipelineConfig) -> dict[str, ModelSpec]:
        role_names = {requirement.name for requirement in scenario.roles}
        bindings: dict[str, ModelSpec] = {}
        for role, ref in config.roles.items():
            if role in role_names:
                bindings[role] = self._spec(ref)
        if WILDCARD_ROLE in config.roles:
            for requirement in scenario.roles:
                # Optional roles with a fallback keep their fallback semantics (e.g. critic = generator).
                if requirement.name not in bindings and requirement.fallback is None:
                    bindings[requirement.name] = self._spec(config.roles[WILDCARD_ROLE])
        return bindings

    def _spec(self, ref: str) -> ModelSpec:
        try:
            return resolve_model(ref, self.model_specs, self.catalog.specs() if self.catalog else None)
        except KeyError as exc:
            raise ConfigError(str(exc)) from exc

    def _client(self, spec: ModelSpec) -> LLMClient:
        if spec.name not in self._clients:
            self._clients[spec.name] = self.budget.wrap(self.runtime.client_factory(spec))
        return self._clients[spec.name]

    # ---- execution ------------------------------------------------------------------------
    async def preflight(self) -> list[TrialSpec]:
        """Resolve models, plan trials and build every client now, so configuration errors (unknown model,
        missing capability, missing key, unsupported provider) surface before anything runs."""
        await self.prepare()
        trials = self.plan()
        specs = {spec.name: spec for trial in trials for spec in trial.bindings.values()}
        if self.judge_spec is not None:
            specs[self.judge_spec.name] = self.judge_spec
        for spec in specs.values():
            try:
                self._client(spec)
            except ConfigError:
                raise
            except Exception as exc:
                raise ConfigError(f"{spec.name}: {exc}") from exc
        self._planned = trials
        return trials

    async def run(self) -> str:
        if self.store is None:
            raise ConfigError("ExperimentRunner.run needs a RunStore")
        store = self.store
        trials = self._planned if self._planned is not None else await self.preflight()
        store.start_run(self.run_id, self.experiment.name, self.experiment.model_dump_json())
        done = store.completed_trials()
        pending = [trial for trial in trials if trial.trial_id not in done]
        self.sink(RunStarted(run_id=self.run_id, total=len(trials), pending=len(pending)))
        gate = asyncio.Semaphore(self.experiment.max_parallel_trials)
        endpoint_slots: dict[str, asyncio.Semaphore] = {}
        finished = 0

        async def guarded(trial: TrialSpec) -> None:
            nonlocal finished
            async with gate, contextlib.AsyncExitStack() as stack:
                # Reserve every endpoint the trial uses *before* its clock starts. A local server
                # (concurrency 1) then runs trials one after another instead of interleaving their
                # calls, which would inflate latencies and burn trial timeouts while queued.
                for key, capacity in sorted(_endpoints(trial.bindings.values())):
                    slot = endpoint_slots.setdefault(key, asyncio.Semaphore(capacity))
                    await stack.enter_async_context(slot)
                if self._cancelled or self.budget.exceeded:
                    return
                self.sink(TrialStarted(trial_id=trial.trial_id, scenario=trial.scenario.name, config=trial.config.name,
                                       task_id=trial.task.id, repeat=trial.repeat))  # fmt: skip
                record = await self._run_trial(trial, store)
                finished += 1
                self.sink(TrialFinished(
                    trial_id=record.trial_id, scenario=record.scenario, config=record.config, task_id=record.task_id,
                    repeat=record.repeat, status=record.status, passed=record.passed, duration_s=record.duration_s,
                    cost_usd=record.totals.get("cost_usd", 0.0) + record.judge_cost_usd, done=finished, total=len(pending),
                ))  # fmt: skip
                if self.budget.exceeded and self.budget.limit_usd is not None:
                    self.sink(BudgetExceeded(spent_usd=self.budget.spent_usd, limit_usd=self.budget.limit_usd))

        await asyncio.gather(*(guarded(trial) for trial in pending))
        if self.experiment.arena.enabled and not self._cancelled and not self.budget.exceeded:
            await self._run_battles(store, trials)
        stopped = self._cancelled or self.budget.exceeded
        self.sink(RunFinished(run_id=self.run_id, spent_usd=self.budget.spent_usd, stopped_early=stopped))
        return self.run_id

    async def _run_trial(self, spec: TrialSpec, store: RunStore) -> TrialRecord:
        trace = Trace()
        salt_token = cache_salt.set(f"repeat={spec.repeat}")
        started = time.perf_counter()
        status, error, output = "ok", None, TrialOutput(final="")
        models = RoleModels({role: self._client(model) for role, model in spec.bindings.items()}, trace)
        ctx = RunContext(
            trace=trace, params=spec.params, live=self.live, seed=self.experiment.seed + spec.repeat,
            sandbox=self.runtime.sandbox, live_search=self.runtime.live_search,
        )  # fmt: skip
        try:
            output = await asyncio.wait_for(spec.scenario.run(spec.task, models, ctx), self.experiment.trial_timeout_s)
        except TimeoutError:
            status, error = "timeout", f"trial exceeded {self.experiment.trial_timeout_s}s"
        except BudgetExceededError as exc:
            status, error = "budget", str(exc)
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"
        finally:
            cache_salt.reset(salt_token)
        duration = time.perf_counter() - started

        judge_trace = Trace()
        scores = await self._evaluate(spec, output, trace, judge_trace) if status == "ok" else []
        criteria = set(spec.scenario.pass_criteria)
        graded = [score for score in scores if score.name in criteria and score.passed is not None]
        passed = status == "ok" and bool(graded) and all(score.passed for score in graded)
        record = TrialRecord(
            trial_id=spec.trial_id,
            scenario=spec.scenario.name,
            pattern=spec.scenario.pattern,
            config=spec.config.name,
            task_id=spec.task.id,
            repeat=spec.repeat,
            status=status,
            passed=passed,
            error=error,
            final=output.final,
            duration_s=duration,
            totals=trace.totals(),
            judge_cost_usd=judge_trace.totals()["cost_usd"],
            roles={role: model.name for role, model in spec.bindings.items()},
            params=spec.params,
        )
        extra = {
            "env_state": output.env_state,
            "extras": output.extras,
            "judge_spans": judge_trace.model_dump()["spans"],
        }
        store.save_trial(self.run_id, record, scores, trace, extra)
        return record

    async def _evaluate(self, spec: TrialSpec, output: TrialOutput, trace: Trace, judge_trace: Trace) -> list[Score]:
        judge = TracedLLM(self._client(self.judge_spec), judge_trace, "judge") if self.judge_spec else None
        ctx = EvalContext(
            task=spec.task, output=output, trace=trace, judge=judge, params=spec.params, sandbox=self.runtime.sandbox
        )
        scores: list[Score] = []
        for evaluator in spec.scenario.evaluators(spec.params):
            try:
                scores += await evaluator.evaluate(ctx)
            except Exception as exc:  # a broken evaluator must not lose the trial
                scores.append(Score(name=f"{evaluator.name}.error", value=0.0, level="e2e", rationale=f"{exc}"[:500]))
        return scores

    # ---- arena ----------------------------------------------------------------------------
    async def _run_battles(self, store: RunStore, trials: list[TrialSpec]) -> None:
        judge_ref = self.experiment.arena.judge or self.experiment.judge
        if judge_ref is None:
            return  # arena enabled without a judge: nothing to battle with
        judge = self._client(self._spec(judge_ref))
        scenarios = {trial.scenario.name: trial.scenario for trial in trials if trial.scenario.open_ended}
        tasks = {(trial.scenario.name, trial.task.id): trial.task for trial in trials}
        for name, scenario in scenarios.items():
            finals: dict[str, dict[str, str]] = {}
            for task_id, config, final in store.finals_for_battles(name):
                finals.setdefault(task_id, {})[config] = final
            for task_id, by_config in finals.items():
                pairs = list(itertools.combinations(sorted(by_config), 2))[: self.experiment.arena.max_pairs_per_task]
                for a, b in pairs:
                    if store.has_battle(name, task_id, a, b):
                        continue
                    winner, rationale = await judge_pairwise(
                        judge, tasks[(name, task_id)].prompt, by_config[a], by_config[b], scenario.pairwise_criteria
                    )
                    store.save_battle(name, task_id, a, b, winner, rationale)


def _endpoints(specs: Iterable[ModelSpec]) -> set[tuple[str, int]]:
    return {(f"{spec.provider}|{resolve_base_url(spec)}", resolve_concurrency(spec)) for spec in specs}


def describe_plan(trials: list[TrialSpec]) -> str:
    summary: dict[str, dict[str, int]] = {}
    for trial in trials:
        summary.setdefault(trial.scenario.name, {}).setdefault(trial.config.name, 0)
        summary[trial.scenario.name][trial.config.name] += 1
    return json.dumps(summary, indent=2)
