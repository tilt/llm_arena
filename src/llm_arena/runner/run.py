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
import mimetypes
import re
import time
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from llm_arena.core.errors import ConfigError
from llm_arena.core.trace import Trace
from llm_arena.decisions.config import DECIDER_ROLE, ESCALATION_ROLE, DecisionSetup
from llm_arena.eval.base import EvalContext, Score, Task, TrialOutput, evaluate_all
from llm_arena.eval.credit import trial_credit, trial_passed
from llm_arena.eval.judge import JudgeEvaluator, judge_pairwise
from llm_arena.llm.cache import cache_salt
from llm_arena.llm.catalog import Catalog
from llm_arena.llm.client import LLMClient
from llm_arena.llm.registry import resolve_base_url, resolve_concurrency, resolve_model
from llm_arena.llm.spec import ModelSpec
from llm_arena.patterns.roles import RoleModels, TracedLLM
from llm_arena.runner.budget import BudgetExceededError, BudgetGuard, is_free
from llm_arena.runner.config import ExperimentConfig, PipelineConfig
from llm_arena.runner.events import (
    BudgetExceeded,
    EventSink,
    RunFinished,
    RunStarted,
    RunWarning,
    TrialFinished,
    TrialStarted,
    ignore,
)
from llm_arena.runner.fingerprint import fingerprint, resume_key, setup_of, task_fingerprint
from llm_arena.runner.ports import RunStore, Runtime, TrialRecord
from llm_arena.runner.presets import DEFAULT_PRESETS, ModelPreset
from llm_arena.runner.study import expand as expand_study
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, get_scenario

WILDCARD_ROLE = "*"  # binds every role of a scenario that the config does not bind explicitly
SANDBOX_REQUIRED = (
    "Start Docker and run `make sandbox-image`, or restart with `--sandbox unsafe-process` to run model code as your "
    "user (not isolated)."
)
MAX_PLANNED_TRIALS = 20_000
_RUN_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,119}[A-Za-z0-9])?$")
_WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}


@dataclass
class TrialSpec:
    scenario: Scenario
    config: PipelineConfig
    task: Task
    repeat: int
    bindings: dict[str, ModelSpec]
    params: dict[str, Any]
    seed: int = 0

    @property
    def setup(self) -> dict[str, Any]:
        policy = self.config.decisions
        decisions = policy.model_dump(mode="json") if policy else None
        # Decision roles count only when the policy calls them, so an unused decider never splits a setup.
        unused = {DECIDER_ROLE, ESCALATION_ROLE} - (policy.llm_roles() if policy else set())
        return setup_of({r: m for r, m in self.bindings.items() if r not in unused}, self.params, decisions)

    @property
    def resume_key(self) -> str:
        return resume_key(fingerprint(self.setup), self.scenario.version, task_fingerprint(self.task), self.seed)

    @property
    def trial_id(self) -> str:
        key = f"{self.scenario.name}|{self.config.name}|{self.task.id}|{self.repeat}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]


def new_run_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-_")[:105] or "run"
    return f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"


def valid_run_id(run_id: str) -> bool:
    return bool(_RUN_ID.fullmatch(run_id)) and run_id.split(".", 1)[0].upper() not in _WINDOWS_DEVICE_NAMES


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
        presets: dict[str, ModelPreset] | None = None,
    ) -> None:
        self.experiment = experiment
        self.runtime = runtime
        self.store = store
        self.run_id = run_id or new_run_id(experiment.name)
        if not valid_run_id(self.run_id):
            raise ConfigError(
                "run ids must start with a letter or digit and use at most 121 letters, digits, ., _ or -"
            )
        self.live = live
        self.model_specs = model_specs or {}
        self.catalog = catalog
        self.sink = sink
        self.presets = {**(presets or DEFAULT_PRESETS), **experiment.presets}
        self.budget = BudgetGuard(experiment.max_cost_usd, experiment.budget_mode)
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
        refs |= {ref for c in self.experiment.configs if c.preset for ref in self._preset(c).models.values()}
        if study := self.experiment.study:
            services = tuple(f"{s}:" for s in ("ollaya", "jev"))
            refs |= {c for c in study.candidates if not c.startswith(services)}
            refs |= set(self.presets[study.baseline].models.values()) if study.baseline in self.presets else set()
        refs |= {ref for c in self.experiment.configs for roles in c.scenario_roles.values() for ref in roles.values()}
        refs |= {ref for ref in (self.experiment.judge, self.experiment.arena.judge) if ref}
        return {ref for ref in refs if ref not in self.model_specs}

    async def prepare(self) -> None:
        """Discover installed models once, if any reference needs it."""
        if self.catalog is None and self.unresolved_refs() and self.runtime.discover is not None:
            self.catalog = await self.runtime.discover()

    # ---- planning -------------------------------------------------------------------------
    def plan(self) -> list[TrialSpec]:
        self._expand_study()
        trials: list[TrialSpec] = []
        for scenario_name in self.experiment.scenarios:
            scenario = get_scenario(scenario_name)
            tasks = self._select_tasks(scenario.load_tasks())
            for config in self.experiment.configs:
                if config.scenarios is not None and scenario_name not in config.scenarios:
                    continue
                if config.decisions is not None and not scenario.supports_decisions:
                    raise ConfigError(f"{config.name}: scenario {scenario_name!r} does not support a control policy")
                bindings = scenario.check_roles(self._bind(scenario, config))
                params = scenario.params(config.params_for(scenario_name, set(scenario.default_params)))
                trials += [
                    TrialSpec(scenario, config, task, repeat, bindings, params, self.experiment.seed + repeat)
                    for task in tasks
                    for repeat in range(self.experiment.repeats)
                ]
        return trials

    def _select_tasks(self, tasks: list[Task]) -> list[Task]:
        if self.experiment.task_ids:
            tasks = [task for task in tasks if task.id in set(self.experiment.task_ids)]
        if self.experiment.split != "all":
            tasks = [task for task in tasks if task.data.get("split", self.experiment.split) == self.experiment.split]
        return tasks[: self.experiment.limit] if self.experiment.limit else tasks

    def _bind(self, scenario: Scenario, config: PipelineConfig) -> dict[str, ModelSpec]:
        role_names = {requirement.name for requirement in scenario.roles}
        roles = config.roles_for(scenario.name)  # per-scenario bindings override the config-wide ones
        if extra := set(config.scenario_roles.get(scenario.name, {})) - role_names - {WILDCARD_ROLE}:
            raise ConfigError(
                f"{config.name}: {scenario.name} has no roles {sorted(extra)}; roles: {sorted(role_names)}"
            )
        bindings: dict[str, ModelSpec] = {}
        for role, ref in roles.items():
            if role in role_names:
                bindings[role] = self._spec(ref)
        if config.preset:
            # Precedence: per-scenario binding > config role > the preset's model for the role's kind > "*".
            profile = self._preset(config)
            for requirement in scenario.roles:
                if requirement.name not in bindings:
                    bindings[requirement.name] = self._spec(profile.model_for(requirement.kind))
        if WILDCARD_ROLE in roles:
            for requirement in scenario.roles:
                # Optional roles with a fallback keep their fallback semantics (e.g. critic = generator).
                if requirement.name not in bindings and requirement.fallback is None:
                    bindings[requirement.name] = self._spec(roles[WILDCARD_ROLE])
        return bindings

    def _expand_study(self) -> None:
        """Expand a study into configurations (after any explicit ones), once, when model capabilities are known:
        a candidate replaces only steps it can do. The run records the expanded experiment."""
        study = self.experiment.study
        if study is None or any(c.study for c in self.experiment.configs):
            return
        if study.baseline not in self.presets:
            raise ConfigError(f"study: unknown baseline preset {study.baseline!r}; known: {sorted(self.presets)}")

        def can_do(candidate: str, role: RoleRequirement) -> bool:
            capabilities = self._spec(candidate).capabilities
            return all(getattr(capabilities, need) for need in role.needs)

        scenarios = [get_scenario(name) for name in self.experiment.scenarios]
        generated = expand_study(study, scenarios, self.presets[study.baseline], can_do)
        configs = [*self.experiment.configs, *(PipelineConfig.model_validate(c) for c in generated)]
        self.experiment = self.experiment.model_copy(update={"configs": configs})

    def _preset(self, config: PipelineConfig) -> ModelPreset:
        if config.preset not in self.presets:
            raise ConfigError(f"{config.name}: unknown preset {config.preset!r}; known: {sorted(self.presets)}")
        return self.presets[config.preset]

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
        if len(trials) > MAX_PLANNED_TRIALS:
            raise ConfigError(f"this experiment plans {len(trials)} trials; the maximum is {MAX_PLANNED_TRIALS}")
        needs_sandbox = sorted({trial.scenario.name for trial in trials if "sandbox" in trial.scenario.requires})
        if needs_sandbox and self.runtime.sandbox is None:
            raise ConfigError(SANDBOX_REQUIRED)
        specs = {spec.name: spec for trial in trials for spec in trial.bindings.values()}
        if self.judge_spec is not None:
            specs[self.judge_spec.name] = self.judge_spec
        for spec in specs.values():
            self.budget.validate_spec(spec)
            try:
                self._client(spec)
            except ConfigError:
                raise
            except Exception as exc:
                raise ConfigError(f"{spec.name}: {exc}") from exc
        for config in {trial.config.name: trial.config for trial in trials}.values():
            decisions = config.decisions
            for service in decisions.services() if decisions else set():
                if self.runtime.decision_services is None or decisions is None:
                    raise ConfigError(
                        f"{config.name}: {service} is not available in this runtime ({self.runtime.name})"
                    )
                try:
                    self.runtime.decision_services(service, decisions.service_model(service))
                except Exception as exc:
                    raise ConfigError(f"{config.name}: {exc}") from exc
        self._planned = trials
        return trials

    async def run(self) -> str:
        if self.store is None:
            raise ConfigError("ExperimentRunner.run needs a RunStore")
        store = self.store
        trials = self._planned if self._planned is not None else await self.preflight()
        execution = self.runtime.execution_environment()
        existing = store.load_run()
        self._check_execution_resume(existing, execution)
        store.start_run(
            self.run_id, self.experiment.name, self.experiment.model_dump_json(), json.dumps(execution, sort_keys=True)
        )
        done = store.completed_trials()
        # Resuming may skip a finished trial only if it ran exactly this setup, task version and seed;
        # otherwise the run would silently mix results of two different experiments under one config name.
        stale = sorted({t.config.name for t in trials if done.get(t.trial_id) not in (None, "", t.resume_key)})
        if stale:
            raise ConfigError(
                f"run {self.run_id} already has results for {', '.join(stale)} from a different setup (models, "
                "parameters, control policy, task content or seed changed). Start a new run id instead of resuming."
            )
        pending = [trial for trial in trials if trial.trial_id not in done]
        self.sink(RunStarted(run_id=self.run_id, total=len(trials), pending=len(pending)))
        endpoint_slots: dict[str, asyncio.Semaphore] = {}
        finished = 0
        queue: asyncio.Queue[TrialSpec] = asyncio.Queue()
        for trial in pending:
            queue.put_nowait(trial)
        budget_reported = False

        def report_budget() -> None:
            # Once per run, so parallel trials that all hit the limit don't repeat the stop reason.
            nonlocal budget_reported
            if self.budget.limit_hit and self.budget.limit_usd is not None and not budget_reported:
                budget_reported = True
                self.sink(BudgetExceeded(spent_usd=self.budget.spent_usd, limit_usd=self.budget.limit_usd))

        async def worker() -> None:
            nonlocal finished
            while not queue.empty():
                try:
                    trial = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    async with contextlib.AsyncExitStack() as stack:
                        # Reserve all endpoints before the trial clock starts, preserving measured latency.
                        for key, capacity in sorted(_endpoints(trial.bindings.values())):
                            slot = endpoint_slots.setdefault(key, asyncio.Semaphore(capacity))
                            await stack.enter_async_context(slot)
                        if self._cancelled or self.budget.exceeded:
                            continue
                        # After a refused call, paid trials are recorded as refused without running, so not "started".
                        not_started = self.budget.refused and self._may_pay(trial)
                        if not not_started:
                            self.sink(
                                TrialStarted(
                                    trial_id=trial.trial_id,
                                    scenario=trial.scenario.name,
                                    config=trial.config.name,
                                    task_id=trial.task.id,
                                    repeat=trial.repeat,
                                )
                            )
                        record = await self._run_trial(trial, store, not_started=not_started)
                        finished += 1
                        self.sink(
                            TrialFinished(
                                trial_id=record.trial_id,
                                scenario=record.scenario,
                                config=record.config,
                                task_id=record.task_id,
                                repeat=record.repeat,
                                status=record.status,
                                passed=record.passed,
                                duration_s=record.duration_s,
                                cost_usd=record.totals.get("cost_usd", 0.0) + record.judge_cost_usd,
                                done=finished,
                                total=len(pending),
                            )
                        )
                        report_budget()
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(min(self.experiment.max_parallel_trials, len(pending)))]
        await asyncio.gather(*workers)
        if self.experiment.arena.enabled and not self._cancelled and not self.budget.exceeded:
            await self._run_battles(store, trials)
        report_budget()
        stopped = self._cancelled or self.budget.limit_hit
        self.sink(RunFinished(run_id=self.run_id, spent_usd=self.budget.spent_usd, stopped_early=stopped))
        return self.run_id

    async def _run_trial(self, spec: TrialSpec, store: RunStore, *, not_started: bool = False) -> TrialRecord:
        trace = Trace()
        store.clear_artifacts(spec.trial_id)  # a retried trial starts clean
        trace.store_artifacts_with(lambda name, data, media: store.save_artifact(spec.trial_id, name, data, media))
        salt_token = cache_salt.set(f"repeat={spec.repeat}")
        started = time.perf_counter()
        status, error, output = "ok", None, TrialOutput(final="")
        models = RoleModels({role: self._client(model) for role, model in spec.bindings.items()}, trace)
        ctx = RunContext(
            trace=trace, params=spec.params, live=self.live, seed=self.experiment.seed + spec.repeat,
            sandbox=self.runtime.sandbox, live_search=self.runtime.live_search, decisions=self._decisions(spec, trace),
        )  # fmt: skip
        try:
            if not_started:
                # A paid call was already turned away, so this trial's may be too: record why, skip setup and spend.
                raise BudgetExceededError(f"spend limit of ${self.budget.limit_usd:.2f} reached; trial not started")
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
        if output.artifacts or output.final:
            # The result as its own step, so the inspector shows the final answer and produced files.
            with trace.in_step("end"), trace.span("step", "result") as result_span:
                result_span.output = output.final
                for name, data in output.artifacts.items():
                    trace.attach(result_span, name, data, mimetypes.guess_type(name)[0] or "application/octet-stream")

        judge_trace = Trace()
        scores = await self._evaluate(spec, output, trace, judge_trace) if status == "ok" else []
        passed = trial_passed(status, scores, spec.scenario.pass_criteria)
        credit, criteria_detail = trial_credit(status, scores, spec.scenario.pass_criteria)
        setup = spec.setup
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
            fingerprint=fingerprint(setup),
            scenario_version=spec.scenario.version,
            task_fp=task_fingerprint(spec.task),
            setup=setup,
            resume_key=spec.resume_key,
            execution=self.runtime.execution_environment(),
            credit=credit,
            criteria=criteria_detail,
            unpriced=sorted(role for role, model in spec.bindings.items() if role in setup["roles"] and is_free(model)),
        )
        extra = {
            "env_state": output.env_state,
            "extras": output.extras,
            "judge_spans": judge_trace.model_dump()["spans"],
        }
        store.save_trial(self.run_id, record, scores, trace, extra)
        return record

    def _may_pay(self, spec: TrialSpec) -> bool:
        """Whether a trial can call anything priced: a role model not known to be free, the judge when the scenario
        grades with one, or a paid decision service (Jev)."""
        models = list(spec.bindings.values())
        evaluators = spec.scenario.evaluators(spec.params)
        if self.judge_spec and any(isinstance(evaluator, JudgeEvaluator) for evaluator in evaluators):
            models.append(self.judge_spec)
        decisions = spec.config.decisions
        return not all(is_free(model) for model in models) or bool(decisions and decisions.paid_services())

    def _check_execution_resume(self, existing: Any, current: dict[str, str]) -> None:
        completed_code = [
            trial
            for trial in existing.trials
            if trial.get("status") == "ok" and "sandbox" in get_scenario(str(trial.get("scenario"))).requires
        ]
        if not completed_code:
            return
        raw = existing.run.get("execution_json")
        previous = json.loads(raw) if raw else {}
        previous_isolation = str(previous.get("isolation", ""))
        if previous_isolation and previous_isolation != current["isolation"]:
            raise ConfigError(
                f"This run's code trials ran in {previous_isolation}; resume it with the same sandbox, or start a "
                "new run."
            )
        if not previous_isolation:
            self.sink(RunWarning(message="This legacy run has code trials with unknown sandbox attribution."))
            return
        changed = [
            field
            for field in ("backend", "daemon", "image_id", "sandbox_policy", "browser_network")
            if previous.get(field, "") != current.get(field, "")
        ]
        if changed:
            self.sink(
                RunWarning(
                    message=f"The sandbox {', '.join(changed)} changed; resumed trials record the new environment."
                )
            )

    def _decisions(self, spec: TrialSpec, trace: Trace) -> DecisionSetup | None:
        config = spec.config.decisions
        if config is None:
            return None
        clients = {role: TracedLLM(self._client(model), trace, role) for role, model in spec.bindings.items()}
        return DecisionSetup(
            config=config, trace=trace, decider=clients.get(DECIDER_ROLE), escalation=clients.get(ESCALATION_ROLE),
            services=self.runtime.decision_services, budget=self.budget,
        )  # fmt: skip

    async def _evaluate(self, spec: TrialSpec, output: TrialOutput, trace: Trace, judge_trace: Trace) -> list[Score]:
        judge = TracedLLM(self._client(self.judge_spec), judge_trace, "judge") if self.judge_spec else None
        ctx = EvalContext(
            task=spec.task, output=output, trace=trace, judge=judge, params=spec.params, sandbox=self.runtime.sandbox
        )
        return await evaluate_all(spec.scenario.evaluators(spec.params), ctx)

    # ---- arena ----------------------------------------------------------------------------
    async def _run_battles(self, store: RunStore, trials: list[TrialSpec]) -> None:
        judge_ref = self.experiment.arena.judge or self.experiment.judge
        if judge_ref is None:
            return  # arena enabled without a judge: nothing to battle with
        judge_spec = self._spec(judge_ref)
        if self.budget.refused and not is_free(judge_spec):
            return  # a paid call was already turned away, so every paid battle would be too
        judge = self._client(judge_spec)
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
