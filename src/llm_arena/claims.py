"""Shareable claims: one run's result, published so anyone can re-run it and post a reproduction.

A claim says "setup S passes scenario X vN on these tasks at p% for $c per task". It carries the setup and the
results, never prompts, tools or traces: those come from the scenario at that version. Visitors re-run the claimed
setup next to a variant ("Beat this"); the claimed half is a reproduction, posted as a gist comment with one
``arena-repro`` block, and the claim page tallies the reproductions that pass `validate_repro`.

Everything here is pure (no network, no storage), so the local app and the Pyodide engine give identical verdicts;
the conformance vectors replay them in both. Claims are untrusted input: closed schemas, allow-lists, size caps.

Self-hosted models (Ollama, LM Studio, named OpenAI-compatible endpoints) travel as a *portable role*:
``provider: "self_hosted"`` with a "compare as" name the person declares. Endpoint names, their identities and URLs
never leave the machine; a visitor matches the role with any of their own models declared under that name.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from llm_arena.decisions.config import DECIDER_ROLE, ESCALATION_ROLE, DecisionConfig
from llm_arena.eval.judge import JudgeEvaluator
from llm_arena.llm.pricing import known_price
from llm_arena.llm.spec import ModelSpec, ReasoningEffort
from llm_arena.runner.config import COMPARE_NAME, ClaimRef, ExperimentConfig, PipelineConfig
from llm_arena.runner.fingerprint import _digest, fingerprint, task_fingerprint
from llm_arena.runner.ports import RunData
from llm_arena.runner.study import StudyTag
from llm_arena.scenarios.base import SCENARIOS, Scenario, get_scenario

CLAIM_FORMAT = 1
MAX_CLAIM_BYTES = 256 * 1024
MAX_TASKS = 500
MAX_REPEATS = 20
MAX_SEEN = 300
CLAIMED_CONFIG = "claimed-setup"
VARIANT_CONFIG_PREFIX = "swap"
SHARED_PROVIDERS = ("openai", "anthropic")
SELF_HOSTED = "self_hosted"
LOCAL_PROVIDERS = ("ollama", "lmstudio", "openai_compatible")
Engine = Literal["pages", "local"]
_HEX64 = r"^[0-9a-f]{64}$"
_ROLE = r"^[a-z_][a-z0-9_]{0,40}$"
_MODEL_ID = re.compile(r"^[^\s#]{1,200}$")
REPRO_FENCE = "arena-repro"
_REPRO_OPEN = re.compile(r"```" + REPRO_FENCE + r"[ \t]*\n")


# ---- formats ---------------------------------------------------------------------------------------------------
class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimRole(_Closed):
    """A role's model as it travels: the call settings of `runner.fingerprint.SPEC_FIELDS`, no endpoint fields."""

    provider: Literal["openai", "anthropic", "self_hosted"]
    model: str = Field(description="the provider's model id, or a self-hosted model's declared 'compare as' name")
    backend: Literal["auto"] = "auto"
    tool_mode: Literal["native", "json"] = "native"
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    reasoning_effort: ReasoningEffort | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def _model_name(self) -> ClaimRole:
        if self.provider == SELF_HOSTED and not COMPARE_NAME.fullmatch(self.model):
            raise ValueError(f"self-hosted name {self.model!r}: use lowercase letters, digits, . and -; up to 64")
        if not _MODEL_ID.fullmatch(self.model):
            raise ValueError(f"invalid model id {self.model[:40]!r}")
        return self


class ClaimSetup(_Closed):
    roles: dict[str, ClaimRole] = Field(min_length=1, max_length=16)
    params: dict[str, Any] = Field(default_factory=dict, max_length=32)
    decisions: dict[str, Any] | None = None

    @field_validator("roles")
    @classmethod
    def _role_names(cls, roles: dict[str, ClaimRole]) -> dict[str, ClaimRole]:
        for name in roles:
            if not re.fullmatch(_ROLE, name):
                raise ValueError(f"invalid role name {name[:40]!r}")
        return roles


class ClaimTask(_Closed):
    id: str = Field(min_length=1, max_length=120)
    fp: str = Field(pattern=r"^[0-9a-f]{8}$")


class ClaimResult(_Closed):
    passed: int = Field(ge=0)
    trials: int = Field(ge=1)
    pass_rate: float = Field(ge=0, le=1)
    partial: float = Field(ge=0, le=1)
    cost_usd_per_task: float = Field(ge=0, description="priced roles only")
    unpriced_roles: list[str] = Field(default_factory=list, max_length=16, description="roles whose cost is unknown")
    engine: Engine


class Claim(_Closed):
    arena_claim: Literal[1]
    scenario: str = Field(min_length=1, max_length=64)
    scenario_version: str = Field(min_length=1, max_length=16)
    tasks: list[ClaimTask] = Field(min_length=1, max_length=MAX_TASKS)
    task_fps_hash: str = Field(pattern=r"^[0-9a-f]{12}$")
    seed: int = Field(ge=0, le=2**31)
    repeats: int = Field(ge=1, le=MAX_REPEATS)
    setup: ClaimSetup
    setup_fp: str = Field(pattern=r"^[0-9a-f]{12}$")
    judge: ClaimRole | None = Field(default=None, description="the LLM judge that graded it; None: code checks only")
    result: ClaimResult
    made_at: str = Field(max_length=40)
    arena_version: str = Field(max_length=40)
    parent_claim_hash: str | None = Field(default=None, pattern=_HEX64)


class ReproSide(_Closed):
    setup_fp: str = Field(pattern=r"^[0-9a-f]{12}$")
    passed: int = Field(ge=0)
    trials: int = Field(ge=0)
    errors: int = Field(ge=0)
    timeouts: int = Field(ge=0)
    budget_stopped: int = Field(ge=0)
    cost_usd_per_task: float = Field(ge=0)


class ReproVariant(ReproSide):
    setup: ClaimSetup


class PerTask(_Closed):
    b: int = Field(ge=0)
    v: int | None = Field(default=None, ge=0)


class Repro(_Closed):
    arena_repro: Literal[1]
    claim_hash: str = Field(pattern=_HEX64)
    scenario_version: str = Field(max_length=16)
    task_fps_hash: str = Field(pattern=r"^[0-9a-f]{12}$")
    judge: ClaimRole | None = None
    baseline: ReproSide
    variant: ReproVariant | None = None
    per_task: list[PerTask] = Field(max_length=MAX_TASKS)
    seen: list[int] = Field(default_factory=list, max_length=MAX_SEEN, description="comment ids counted at post time")
    engine: Engine
    arena_version: str = Field(max_length=40)


# ---- hashing and portable setups -------------------------------------------------------------------------------
def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def claim_hash(claim: Claim) -> str:
    """Full-length SHA-256 of the canonical claim, so nobody can grind a free field into a collision."""
    return hashlib.sha256(canonical(claim.model_dump(mode="json")).encode()).hexdigest()


def task_fps_hash(tasks: Iterable[ClaimTask]) -> str:
    return _digest([[task.id, task.fp] for task in tasks])


def setup_fingerprint(setup: ClaimSetup) -> str:
    return fingerprint(setup.model_dump(mode="json"))


def local_model(role_setup: Mapping[str, Any]) -> str:
    """The key a self-hosted model is remembered and declared under: '<endpoint or provider>:<model>'."""
    owner = role_setup.get("endpoint") or role_setup.get("provider")
    return f"{owner}:{role_setup.get('model')}"


def portable_role(role_setup: Mapping[str, Any], names: Mapping[str, str]) -> ClaimRole:
    """A trial's role setup (`setup_of` output) as it travels. Self-hosted models need a declared name."""
    provider = role_setup.get("provider")
    model = str(role_setup.get("model"))
    if provider in LOCAL_PROVIDERS:
        key = local_model(role_setup)
        name = names.get(key)
        if not name:
            raise ClaimError(f"{key} needs a 'compare as' name")
        provider, model = SELF_HOSTED, name
    elif provider not in SHARED_PROVIDERS:
        raise ClaimError(f"provider {provider!r} cannot be shared")
    if role_setup.get("backend", "auto") != "auto":
        raise ClaimError(f"{model} runs on backend {role_setup.get('backend')!r}; claims use the default backend")
    try:
        return ClaimRole(
            provider=provider,
            model=model,
            tool_mode=role_setup.get("tool_mode", "native"),
            temperature=role_setup.get("temperature"),
            reasoning_effort=role_setup.get("reasoning_effort"),
            max_tokens=role_setup.get("max_tokens"),
        )
    except ValidationError as exc:
        raise ClaimError(_first_error(exc)) from exc


def portable_setup(setup: Mapping[str, Any], names: Mapping[str, str]) -> ClaimSetup:
    roles = {role: portable_role(spec, names) for role, spec in dict(setup.get("roles") or {}).items()}
    return ClaimSetup(roles=roles, params=dict(setup.get("params") or {}), decisions=setup.get("decisions"))


def portable_spec(spec: ModelSpec, names: Mapping[str, str]) -> ClaimRole:
    return portable_role({field: getattr(spec, field) for field in _SPEC_KEYS} | {"endpoint": spec.endpoint}, names)


_SPEC_KEYS = ("provider", "model", "backend", "tool_mode", "temperature", "reasoning_effort", "max_tokens")


def role_ref(role: ClaimRole, local: str | None = None) -> str:
    """A model reference that resolves to exactly this role's settings (`llm.registry` settings after '#').

    `local`: the visitor's own model standing in for a self-hosted role ('ollama:qwen3:14b', 'gpu-box:Qwen3-14B')."""
    if role.provider == SELF_HOSTED:
        if not local:
            raise ClaimError(f"self-hosted {role.model} needs one of your models declared as {role.model}")
        base = local.partition("#")[0]
    else:
        base = f"{role.provider}:{role.model}"
    settings = [f"tools={role.tool_mode}", f"temperature={'none' if role.temperature is None else role.temperature}"]
    if role.reasoning_effort is not None:
        settings.append(f"reasoning={role.reasoning_effort}")
    if role.max_tokens is not None:
        settings.append(f"max_tokens={role.max_tokens}")
    return f"{base}#{','.join(settings)}"


def suggest_name(model_id: str) -> str:
    """A first "compare as" suggestion for a self-hosted model id (the person confirms or edits it):
    'qwen3:14b' -> 'qwen3-14b', 'Qwen/Qwen3-14B-AWQ' -> 'qwen3-14b-awq'."""
    name = model_id.rsplit("/", 1)[-1].lower()
    name = re.sub(r"[/:_\s]+", "-", name)
    name = re.sub(r"[^a-z0-9.-]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-.")
    return name[:64].rstrip("-.") or "model"


class ClaimError(ValueError):
    """A claim, reproduction or run that cannot be used, with the reason in plain words."""


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error.get("loc", ()))
    return f"{where}: {error.get('msg', 'invalid')}" if where else str(error.get("msg", "invalid"))


# ---- scenario rules --------------------------------------------------------------------------------------------
def _scenario(name: str) -> Scenario:
    get_scenario("email_assistant")  # importing registers every scenario
    if name not in SCENARIOS:
        raise ClaimError(f"unknown scenario {name!r}")
    scenario = get_scenario(name)
    if scenario.kind != "pattern":
        raise ClaimError(f"{name} is a benchmark: benchmark claims would redistribute dataset content")
    return scenario


def uses_judge(scenario: Scenario, params: Mapping[str, Any]) -> bool:
    return any(isinstance(evaluator, JudgeEvaluator) for evaluator in scenario.evaluators(dict(params)))


def check_params(scenario: Scenario, params: Mapping[str, Any]) -> None:
    for key, value in params.items():
        if key not in scenario.default_params:
            raise ClaimError(f"{scenario.name} has no param {key!r}")
        if value != scenario.default_params[key] and value not in scenario.param_choices.get(key, []):
            raise ClaimError(f"param {key}={value!r} is neither the default nor one of its choices")
    if scenario.needs_live(scenario.params(dict(params))):
        raise ClaimError(f"{scenario.name} with these params needs live services; visitors could not reproduce it")


def check_decisions(scenario: Scenario, decisions: Mapping[str, Any] | None) -> DecisionConfig | None:
    if decisions is None:
        return None
    if not scenario.supports_decisions:
        raise ClaimError(f"{scenario.name} does not support a control policy")
    try:
        config = DecisionConfig.model_validate(dict(decisions))
    except ValidationError as exc:
        raise ClaimError(f"decisions: {_first_error(exc)}") from exc
    if config.model_dump(mode="json") != dict(decisions):
        raise ClaimError("decisions carry unknown or non-canonical fields")
    return config


def called_roles(scenario: Scenario, decisions: DecisionConfig | None) -> set[str]:
    """Roles a setup actually calls: every model role, decision roles only when the policy calls them."""
    unused = {DECIDER_ROLE, ESCALATION_ROLE} - (decisions.llm_roles() if decisions else set())
    return {role.name for role in scenario.roles} - unused


def _price_problem(role: ClaimRole, name: str) -> str | None:
    if role.provider == SELF_HOSTED:
        return None  # self-hosted: not priced, so no cap applies to it
    if known_price(role.model) is None:
        return f"{name} ({role.model}) has no known price; strict budgets can't run it"
    if role.max_tokens is None:
        return f"set max_tokens on {name} (e.g. #max_tokens=4096) and re-run to make this claimable"
    return None


# ---- claim validation and drift --------------------------------------------------------------------------------
ClaimState = Literal["ok", "grading_drift", "task_drift", "newer_version"]


class ClaimCheck(BaseModel):
    """A loaded claim, after validation: the claim, its hash, whether it can be run here and now, and why not."""

    claim: Claim
    claim_hash: str
    state: ClaimState
    message: str = ""
    swappable_roles: list[str] = Field(default_factory=list)
    uses_judge: bool = False


def parse_claim(text: str) -> Claim:
    if len(text.encode()) > MAX_CLAIM_BYTES:
        raise ClaimError("this claim is larger than 256 KB")
    try:
        return Claim.model_validate_json(text)
    except ValidationError as exc:
        raise ClaimError(_first_error(exc)) from exc


def check_claim(text: str) -> ClaimCheck:
    """Validate an untrusted claim. Raises ClaimError for anything malformed or not allowed; returns its state."""
    claim = parse_claim(text)
    scenario = _scenario(claim.scenario)
    check_params(scenario, claim.setup.params)
    decisions = check_decisions(scenario, claim.setup.decisions)
    known_roles = {role.name for role in scenario.roles}
    if extra := set(claim.setup.roles) - known_roles:
        raise ClaimError(f"{scenario.name} has no roles {sorted(extra)}")
    bound = set(claim.setup.roles)
    for requirement in scenario.roles:  # optional roles fall back like Scenario.check_roles does
        if requirement.name not in bound and requirement.fallback in bound:
            bound.add(requirement.name)
    if missing := called_roles(scenario, decisions) - bound:
        raise ClaimError(f"the setup has no model for {', '.join(sorted(missing))}")
    judged = uses_judge(scenario, scenario.params(dict(claim.setup.params)))
    if judged and claim.judge is None:
        raise ClaimError(f"{scenario.name} is graded by an LLM judge, so a claim on it must pin that judge")
    if setup_fingerprint(claim.setup) != claim.setup_fp:
        raise ClaimError("setup_fp does not match the setup")
    if task_fps_hash(claim.tasks) != claim.task_fps_hash:
        raise ClaimError("task_fps_hash does not match the tasks")
    if len({task.id for task in claim.tasks}) != len(claim.tasks):
        raise ClaimError("duplicate task ids")
    result = claim.result
    if result.trials != len(claim.tasks) * claim.repeats or result.passed > result.trials:
        raise ClaimError("the result does not match the tasks and repeats")
    if abs(result.pass_rate - result.passed / result.trials) > 1e-6:
        raise ClaimError("pass_rate does not match passed / trials")
    for name, role in claim.setup.roles.items():
        if problem := _price_problem(role, name):
            raise ClaimError(problem)
    if claim.judge is not None and (problem := _price_problem(claim.judge, "judge")):
        raise ClaimError(problem)
    if claim.judge is not None and not judged:
        raise ClaimError(f"{scenario.name} has no judge-graded criteria, so a claim on it pins no judge")
    state, message = _drift(scenario, claim)
    return ClaimCheck(
        claim=claim, claim_hash=claim_hash(claim), state=state, message=message,
        swappable_roles=sorted(called_roles(scenario, decisions) & set(claim.setup.roles)), uses_judge=judged,
    )  # fmt: skip


def _drift(scenario: Scenario, claim: Claim) -> tuple[ClaimState, str]:
    made, now = claim.scenario_version, scenario.version
    if made == now:
        current = {task.id: task for task in scenario.load_tasks()}
        for task in claim.tasks:
            if task.id not in current or task_fingerprint(current[task.id]) != task.fp:
                raise ClaimError("the task set changed without a version bump (likely an arena bug)")
        return "ok", ""
    if made in scenario.regrades_from:
        return "grading_drift", (
            f"Made on v{made}; grading changed since, and reproductions now run v{now}. Author: run "
            "`arena regrade --apply` on the source run, then share it again."
        )
    if _version_key(made) > _version_key(now):
        return "newer_version", f"Made on v{made}, newer than this arena's v{now}. Update the arena to reproduce it."
    return "task_drift", f"Made on v{made}; v{now} changed the tasks. This claim can't be reproduced anymore."


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


# ---- making a claim from a run ---------------------------------------------------------------------------------
class ClaimDraft(BaseModel):
    """What Share as claim would publish (`claim_json`, its hash), or every reason it can't, in plain words."""

    claim_json: str | None = None
    claim_hash: str | None = None
    reasons: list[str] = Field(default_factory=list)
    self_hosted: list[str] = Field(default_factory=list, description="local models that need a 'compare as' name")


def _config_json(data: RunData) -> dict[str, Any]:
    value = json.loads(data.run.get("config_json") or "{}")
    return value if isinstance(value, dict) else {}


def _setup(trial: Mapping[str, Any]) -> dict[str, Any]:
    raw = trial.get("setup") or trial.get("setup_json") or "{}"
    value = json.loads(raw) if isinstance(raw, str) else raw
    return value if isinstance(value, dict) else {}


def self_hosted_models(setups: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted({
        local_model(spec) for setup in setups for spec in dict(setup.get("roles") or {}).values()
        if spec.get("provider") in LOCAL_PROVIDERS
    })  # fmt: skip


def claim_from_run(
    data: RunData,
    names: Mapping[str, str],
    *,
    engine: Engine,
    made_at: str,
    arena_version: str,
    config: str | None = None,
    judge: ModelSpec | None = None,
) -> ClaimDraft:
    """Build the claim Share as claim would publish. `config`: the configuration to share (default: the run's only
    one; a Beat-this run's variant for "Share my variant"). `judge`: the run's judge, resolved by the caller."""
    reasons: list[str] = []
    experiment = _config_json(data)
    trials = [t for t in data.trials if config is None or t.get("config") == config]
    configs = sorted({str(t.get("config")) for t in trials})
    scenarios = sorted({str(t.get("scenario")) for t in trials})
    local = self_hosted_models(_setup(t) for t in trials)
    if not trials:
        return ClaimDraft(reasons=["this run has no finished trials"])
    if len(configs) != 1:
        return ClaimDraft(reasons=["a claim comes from one setup; this run has several"], self_hosted=local)
    if len(scenarios) != 1:
        return ClaimDraft(reasons=["a claim covers one scenario; this run has several"], self_hosted=local)
    try:
        scenario = _scenario(scenarios[0])
    except ClaimError as exc:
        return ClaimDraft(reasons=[str(exc)], self_hosted=local)
    setups = {canonical(_setup(t)) for t in trials}
    if len(setups) != 1:
        reasons.append("the setup changed between trials")
    versions = {str(t.get("scenario_version")) for t in trials}
    if versions != {scenario.version}:
        reasons.append(f"made on {scenario.name} v{', v'.join(sorted(versions))}; re-run it on v{scenario.version}")
    statuses = [str(t.get("status")) for t in trials]
    if bad := sum(status != "ok" for status in statuses):
        reasons.append(f"{bad} trial{'s' if bad != 1 else ''} errored, timed out or hit the spend limit")
    repeats = int(experiment.get("repeats") or 1)
    by_task: dict[str, list[Mapping[str, Any]]] = {}
    for trial in trials:
        by_task.setdefault(str(trial.get("task_id")), []).append(trial)
    if any(len(rows) != repeats for rows in by_task.values()):
        reasons.append("every task needs the same number of finished repeats")
    order = [task.id for task in scenario.load_tasks() if task.id in by_task]
    tasks = [ClaimTask(id=task_id, fp=str(by_task[task_id][0].get("task_fp"))) for task_id in order]
    setup_raw = _setup(trials[0])
    try:
        setup = portable_setup(setup_raw, names)
        check_params(scenario, setup.params)
        check_decisions(scenario, setup.decisions)
    except ClaimError as exc:
        reasons.append(str(exc))
        return ClaimDraft(reasons=reasons, self_hosted=local)
    for name, role in setup.roles.items():
        if problem := _price_problem(role, name):
            reasons.append(problem)
    judge_role: ClaimRole | None = None
    if uses_judge(scenario, setup.params) and judge is None:
        reasons.append(f"{scenario.name} is graded by an LLM judge; set a judge and re-run to make this claimable")
    elif uses_judge(scenario, setup.params) and judge is not None:
        try:
            judge_role = portable_spec(judge, names)
        except ClaimError as exc:
            reasons.append(f"judge: {exc}")
        else:
            if problem := _price_problem(judge_role, "judge"):
                reasons.append(problem)
    if reasons:
        return ClaimDraft(reasons=reasons, self_hosted=local)
    passed = sum(bool(t.get("passed")) for t in trials)
    pass_rate = sum(sum(bool(t.get("passed")) for t in rows) / len(rows) for rows in by_task.values()) / len(by_task)
    partial = sum(sum(float(t.get("credit") or 0) for t in rows) / len(rows) for rows in by_task.values()) / len(
        by_task
    )
    cost = sum(float(t.get("cost_usd") or 0) for t in trials) / len(by_task)
    parent = (experiment.get("claim_ref") or {}).get("claim_hash") if config else None
    claim = Claim(
        arena_claim=1, scenario=scenario.name, scenario_version=scenario.version, tasks=tasks,
        task_fps_hash=task_fps_hash(tasks), seed=int(experiment.get("seed") or 0), repeats=repeats, setup=setup,
        setup_fp=setup_fingerprint(setup), judge=judge_role,
        result=ClaimResult(
            passed=passed, trials=len(trials), pass_rate=round(pass_rate, 6), partial=round(min(1.0, partial), 6),
            cost_usd_per_task=round(cost, 8), engine=engine,
            unpriced_roles=sorted(name for name, role in setup.roles.items() if role.provider == SELF_HOSTED),
        ),
        made_at=made_at, arena_version=arena_version, parent_claim_hash=parent,
    )  # fmt: skip
    text = canonical(claim.model_dump(mode="json"))
    return ClaimDraft(claim_json=text, claim_hash=claim_hash(claim), self_hosted=local)


# ---- Beat this: what runs ---------------------------------------------------------------------------------------
class Swap(BaseModel):
    """The visitor's one change: a role's model, or (local app) the control policy's decision service."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    candidate: str | None = Field(default=None, max_length=300, description="a model reference")
    decisions: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_change(self) -> Swap:
        if (self.role is None) == (self.decisions is None) or (self.role is not None and not self.candidate):
            raise ValueError("a swap changes either one role (role + candidate) or the decisions")
        return self


def inherit_max_tokens(candidate: str, max_tokens: int | None) -> str:
    """The candidate keeps the replaced role's max_tokens unless it sets its own, so the pair differs only in the
    model (and strict budgets can bound it)."""
    if max_tokens is None or "max_tokens=" in candidate.partition("#")[2]:
        return candidate
    return f"{candidate}{',' if '#' in candidate else '#'}max_tokens={max_tokens}"


def claim_experiment(
    check: ClaimCheck,
    *,
    local: Mapping[str, str],
    swap: Swap | None,
    cap_usd: float | None,
    gist: tuple[str, str] | None,
    declared_names: Mapping[str, str],
    judge_local: str | None = None,
) -> ExperimentConfig:
    """The run for "Beat this": the claimed setup (the reproduction) and, with a swap, a variant compared to it.

    `local`: role -> the visitor's model standing in for each self-hosted role of the claim. `cap_usd`: the strict
    spend limit (None when nothing is priced). `gist`: (id, revision) of a gist claim, None for a hash link."""
    if check.state != "ok":
        raise ClaimError(check.message or "this claim can't be reproduced here")
    claim = check.claim
    roles = {name: role_ref(role, local.get(name)) for name, role in claim.setup.roles.items()}
    decisions = DecisionConfig.model_validate(claim.setup.decisions) if claim.setup.decisions else None
    configs = [
        PipelineConfig(name=CLAIMED_CONFIG, roles=roles, params=dict(claim.setup.params), decisions=decisions,
                       study=StudyTag(kind="baseline")),
    ]  # fmt: skip
    if swap is not None:
        if swap.role is not None and swap.candidate is not None:
            if swap.role not in check.swappable_roles:
                raise ClaimError(f"{swap.role} is not a role this setup calls")
            candidate = inherit_max_tokens(swap.candidate, claim.setup.roles[swap.role].max_tokens)
            configs.append(PipelineConfig(
                name=f"{VARIANT_CONFIG_PREFIX}-{swap.role}", roles={**roles, swap.role: candidate},
                params=dict(claim.setup.params), decisions=decisions, compare_to=CLAIMED_CONFIG,
                study=StudyTag(kind="swap", role=swap.role, candidate=candidate),
            ))  # fmt: skip
        else:
            variant = check_decisions(_scenario(claim.scenario), swap.decisions)
            if variant is None or not _policy_swap(decisions, variant):
                raise ClaimError("a control-policy swap must switch to one decision service and change nothing else")
            configs.append(PipelineConfig(
                name=f"{VARIANT_CONFIG_PREFIX}-decisions", roles=roles, params=dict(claim.setup.params),
                decisions=variant, compare_to=CLAIMED_CONFIG,
                study=StudyTag(kind="swap", role="decisions", candidate=f"{variant.policy}:{_service_model(variant)}"),
            ))  # fmt: skip
    judge = role_ref(claim.judge, judge_local) if claim.judge is not None else None
    ref = ClaimRef(gist_id=gist[0] if gist else None, revision=gist[1] if gist else None,
                   claim_hash=check.claim_hash, declared_names=dict(declared_names))  # fmt: skip
    return ExperimentConfig(
        name=f"claim-{claim.scenario}", scenarios=[claim.scenario], configs=configs,
        task_ids=[task.id for task in claim.tasks], repeats=claim.repeats, seed=claim.seed, judge=judge,
        max_cost_usd=cap_usd, budget_mode="strict", claim_ref=ref,
    )  # fmt: skip


def _service_model(config: DecisionConfig) -> str:
    if config.policy == "jev" or config.policy == "ollaya":
        return config.service_model(config.policy)
    return ""


def _policy_swap(claimed: DecisionConfig | None, variant: DecisionConfig) -> bool:
    """Shape (b) of rule 8: the variant's policy is one decision service and nothing but its model differs from that
    policy's defaults (the control mode may follow the claim)."""
    if variant.policy not in ("jev", "ollaya") or variant.services() != {variant.policy}:
        return False
    expected = DecisionConfig(policy=variant.policy, control=variant.control,
                              **{f"{variant.policy}_model": _service_model(variant)})  # fmt: skip
    return variant.model_dump(mode="json") == expected.model_dump(mode="json") and (
        claimed is None or claimed.model_dump(mode="json") != variant.model_dump(mode="json")
    )


def candidate_problem(
    check: ClaimCheck, role: str, spec: ModelSpec, *, engine: Engine, names: Mapping[str, str]
) -> str | None:
    """Why a model can't be this role's Beat-this candidate (None: it can). The page lists only candidates without a
    problem, and `claim_experiment`'s callers refuse the others, so a visitor never pays for an unpostable run."""
    claim = check.claim
    if role not in check.swappable_roles:
        return f"{role} is not called by this setup"
    if spec.provider in ("ollama", "lmstudio") and engine == "pages":
        return "local models run in the local app only"
    if spec.backend != "auto":
        return f"backend {spec.backend} can't be shared"
    requirement = next(r for r in _scenario(claim.scenario).roles if r.name == role)
    if missing := [need for need in sorted(requirement.needs) if not getattr(spec.capabilities, need)]:
        return f"can't do {', '.join(missing)}"
    key = local_model({"provider": spec.provider, "model": spec.model, "endpoint": spec.endpoint})
    # A self-hosted pick gets its name after it is chosen (design 13.11): check it with the suggestion meanwhile.
    named = {key: suggest_name(spec.model), **names} if spec.provider in LOCAL_PROVIDERS else names
    try:
        inherited = spec.with_overrides(max_tokens=spec.max_tokens or claim.setup.roles[role].max_tokens)
        candidate = portable_spec(inherited, named)
    except ClaimError as exc:
        return str(exc)
    claimed = claim.setup.roles[role]
    if (candidate.provider, candidate.model) == (claimed.provider, claimed.model):
        return f"same model as the claim ({claimed.model})"
    return _price_problem(candidate, role)


# ---- reproductions ---------------------------------------------------------------------------------------------
class ReproDraft(BaseModel):
    """The reproduction block a finished claim run would post, or why it can't be posted."""

    block: str | None = None
    repro: Repro | None = None
    reasons: list[str] = Field(default_factory=list)
    variant_config: str | None = None


def repro_comment(repro: Repro) -> str:
    return f"```{REPRO_FENCE}\n{canonical(repro.model_dump(mode='json'))}\n```"


def repro_from_run(
    data: RunData, check: ClaimCheck, *, engine: Engine, arena_version: str, seen: Iterable[int] = ()
) -> ReproDraft:
    """The reproduction of a finished Beat-this run. The reproduced setup is the configuration whose portable
    fingerprint equals the claim's; the variant is the one that compares to it. Names never matter (renames)."""
    experiment = _config_json(data)
    ref = experiment.get("claim_ref") or {}
    claim = check.claim
    if ref.get("claim_hash") != check.claim_hash:
        return ReproDraft(reasons=["this run doesn't reproduce this claim"])
    names = dict(ref.get("declared_names") or {})
    by_config: dict[str, list[dict[str, Any]]] = {}
    for trial in data.trials:
        by_config.setdefault(str(trial.get("config")), []).append(trial)
    claimed: list[str] = []
    for config, rows in by_config.items():
        try:
            if setup_fingerprint(portable_setup(_setup(rows[0]), names)) == claim.setup_fp:
                claimed.append(config)
        except ClaimError:
            continue
    if len(claimed) != 1:
        why = "no setup in this run matches the claimed one" if not claimed else "two setups match the claimed one"
        return ReproDraft(reasons=[f"This run can't be posted as a reproduction: {why}."])
    base_name = claimed[0]
    entries = [c for c in experiment.get("configs", []) if c.get("compare_to") == base_name]
    variant_name = str(entries[0]["name"]) if len(entries) == 1 and entries[0].get("name") in by_config else None
    if len(entries) > 1:
        return ReproDraft(reasons=["This run can't be posted as a reproduction: it compares several setups."])
    reasons: list[str] = []
    judge_ref = experiment.get("judge")
    run_judge = _judge_from_ref(str(judge_ref), names) if judge_ref else None
    if run_judge != claim.judge:
        reasons.append("it was graded by a different judge than the claim")
    tasks = [task.id for task in claim.tasks]
    baseline, b_counts = _side(by_config[base_name], tasks, claim.repeats, claim.setup_fp)
    variant: ReproVariant | None = None
    v_counts: list[int | None] = [None] * len(tasks)
    if variant_name is not None:
        try:
            setup = portable_setup(_setup(by_config[variant_name][0]), names)
        except ClaimError as exc:
            return ReproDraft(reasons=[f"the variant can't be shared: {exc}"])
        variant_side, counts = _side(by_config[variant_name], tasks, claim.repeats, setup_fingerprint(setup))
        variant = ReproVariant(**variant_side.model_dump(), setup=setup)
        v_counts = list(counts)
    sides: list[tuple[str, ReproSide]] = [("claimed setup", baseline)] + ([("variant", variant)] if variant else [])
    for name, side in sides:
        if side.trials != len(tasks) * claim.repeats:
            reasons.append(f"the {name} didn't finish every task")
        if bad := side.errors + side.timeouts + side.budget_stopped:
            reasons.append(f"{bad} {name} trial{'s' if bad != 1 else ''} errored, timed out or hit the spend limit")
    repro = Repro(
        arena_repro=1, claim_hash=check.claim_hash, scenario_version=claim.scenario_version,
        task_fps_hash=claim.task_fps_hash, judge=run_judge, baseline=baseline,
        variant=variant, per_task=[PerTask(b=b, v=v) for b, v in zip(b_counts, v_counts, strict=True)],
        seen=sorted(set(seen))[-MAX_SEEN:], engine=engine, arena_version=arena_version,
    )  # fmt: skip
    if not reasons and (problem := shape_problem(claim, repro)):
        reasons.append(problem)
    if reasons:
        return ReproDraft(repro=repro, reasons=reasons, variant_config=variant_name)
    return ReproDraft(block=repro_comment(repro), repro=repro, variant_config=variant_name)


def _judge_from_ref(ref: str, names: Mapping[str, str]) -> ClaimRole | None:
    """The run's judge as a portable role, read from its reference (Beat-this runs spell every setting out)."""
    base, _, settings = ref.partition("#")
    provider, _, model = base.partition(":")
    values: dict[str, Any] = {}
    for item in filter(None, settings.split(",")):
        key, _, value = item.partition("=")
        values[key] = value
    try:
        if provider in SHARED_PROVIDERS:
            role_provider, role_model = provider, model
        elif base in names:
            role_provider, role_model = SELF_HOSTED, names[base]
        else:
            return None
        return ClaimRole(
            provider=role_provider, model=role_model, tool_mode=values.get("tools", "native"),
            temperature=None if values.get("temperature") == "none" else float(values.get("temperature", 0.2)),
            reasoning_effort=values.get("reasoning"),
            max_tokens=int(values["max_tokens"]) if "max_tokens" in values else None,
        )  # fmt: skip
    except (ValidationError, ValueError):
        return None


def _side(rows: list[dict[str, Any]], tasks: list[str], repeats: int, setup_fp: str) -> tuple[ReproSide, list[int]]:
    relevant = [row for row in rows if row.get("task_id") in set(tasks)]
    counts = [sum(bool(r.get("passed")) for r in relevant if r.get("task_id") == task) for task in tasks]
    side = ReproSide(
        setup_fp=setup_fp,
        passed=sum(counts), trials=len(relevant),
        errors=sum(r.get("status") == "error" for r in relevant),
        timeouts=sum(r.get("status") == "timeout" for r in relevant),
        budget_stopped=sum(r.get("status") == "budget" for r in relevant),
        cost_usd_per_task=round(sum(float(r.get("cost_usd") or 0) for r in relevant) / max(1, len(tasks)), 8),
    )  # fmt: skip
    return side, [min(count, repeats) for count in counts]


def shape_problem(claim: Claim, repro: Repro) -> str | None:
    """Rule 8: a variant changes exactly one role's model (a), or (local app) only the decision service (b)."""
    variant = repro.variant
    if variant is None:
        return None
    if setup_fingerprint(variant.setup) != variant.setup_fp:
        return "the variant's setup_fp does not match its setup"
    base = claim.setup
    changed = [r for r in set(base.roles) | set(variant.setup.roles) if base.roles.get(r) != variant.setup.roles.get(r)]
    if variant.setup.params != base.params:
        return "the variant changed params"
    if len(changed) == 1 and variant.setup.decisions == base.decisions:
        return None
    if not changed and variant.setup.decisions is not None and variant.setup.decisions != base.decisions:
        try:
            swapped = check_decisions(_scenario(claim.scenario), variant.setup.decisions)
        except ClaimError as exc:
            return f"the variant's control policy: {exc}"
        claimed = DecisionConfig.model_validate(base.decisions) if base.decisions else None
        if swapped is not None and _policy_swap(claimed, swapped):
            return None
    return "the variant must change exactly one role's model, or only the decision service"


def validate_repro(check: ClaimCheck, repro: Repro) -> str | None:
    """Rules 2-8 (rule 1 is parsing, rule 9 the comment's edit state). None: the reproduction counts."""
    claim = check.claim
    if repro.claim_hash != check.claim_hash:
        return "made for another version of this claim"
    if repro.task_fps_hash != claim.task_fps_hash:
        return "made on different tasks"
    if repro.scenario_version != claim.scenario_version:
        return "made on another scenario version"
    if repro.baseline.setup_fp != claim.setup_fp:
        return "the reproduced setup differs from the claim"
    if repro.judge != claim.judge:
        return "graded by a different judge"
    n = len(claim.tasks)
    if len(repro.per_task) != n or any(t.b > claim.repeats or (t.v or 0) > claim.repeats for t in repro.per_task):
        return "per-task counts don't match the claim's tasks and repeats"
    if sum(t.b for t in repro.per_task) != repro.baseline.passed or repro.baseline.trials != n * claim.repeats:
        return "per-task counts don't add up to the reproduced result"
    if repro.variant is not None:
        values = [t.v for t in repro.per_task]
        if any(v is None for v in values) or sum(v or 0 for v in values) != repro.variant.passed:
            return "per-task counts don't add up to the variant's result"
        if repro.variant.trials != n * claim.repeats:
            return "the variant didn't finish every task"
    elif any(t.v is not None for t in repro.per_task):
        return "variant counts without a variant"
    for side in (repro.baseline, repro.variant):
        if side is not None and side.errors + side.timeouts + side.budget_stopped:
            return "the run had errors, timeouts or budget stops"
    return shape_problem(claim, repro)


# ---- the thread: trust statistics ------------------------------------------------------------------------------
class Comment(BaseModel):
    """A gist comment as GitHub returns it (only the fields used here)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    user: str = Field(max_length=100)
    created_at: str = Field(max_length=40)
    updated_at: str = Field(max_length=40)
    body: str = Field(max_length=65_536)

    @model_validator(mode="before")
    @classmethod
    def _github_shape(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("user"), dict):
            data = {**data, "user": str(data["user"].get("login") or "")}
        return data


RowStatus = Literal["counted", "author", "superseded", "rejected", "edited", "filtered"]


class ThreadRow(BaseModel):
    comment_id: int
    user: str
    created_at: str
    status: RowStatus
    reason: str = ""
    engine: Engine | None = None
    baseline_passed: int = 0
    baseline_trials: int = 0
    baseline_cost_usd_per_task: float = 0.0
    variant_role: str | None = None
    variant_model: str | None = None
    variant_passed: int | None = None
    variant_cost_usd_per_task: float | None = None


class TrustStats(BaseModel):
    rows: list[ThreadRow]
    hidden: int = Field(description="comments without a reproduction block")
    people: int = Field(description="distinct non-author reproducers counted")
    passed: int = 0
    trials: int = 0
    rate: float | None = None
    low: float | None = None
    high: float | None = None
    above_interval: bool = Field(default=False, description="claimed rate above the pooled interval (≥3 people)")
    partial: bool = Field(default=False, description="only the first `loaded` of `total` comments were read")
    loaded: int = 0
    total: int = 0
    removed: int = Field(default=0, description="reproductions referenced by later ones but gone from the thread")


def wilson(passed: int, trials: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval of a pass rate."""
    if trials <= 0:
        return 0.0, 1.0
    p = passed / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def parse_repro(body: str) -> Repro | None | str:
    """The comment's reproduction: a Repro, None without a block, or why the block is invalid (rule 1)."""
    # Linear on hostile comments: the first opener's closer is the first "\n```" after it (a regex with a lazy
    # DOTALL group rescans the rest of the body from every opener).
    opener = _REPRO_OPEN.search(body)
    end = body.find("\n```", opener.end()) if opener else -1
    if opener is None or end < 0:
        return None
    try:
        return Repro.model_validate_json(body[opener.end() : end])
    except ValidationError as exc:
        return f"not a valid reproduction block ({_first_error(exc)})"


def trust_stats(
    check: ClaimCheck,
    comments: Iterable[Mapping[str, Any]],
    *,
    author: str,
    total: int | None = None,
    engine: Engine | None = None,
) -> TrustStats:
    """Tally a claim's thread: valid reproductions, latest per GitHub user, the author's own excluded. `total`: how
    many comments the gist has (more than loaded means a partial thread). `engine`: count one engine only."""
    parsed = [Comment.model_validate(dict(c)) for c in comments]
    rows: list[ThreadRow] = []
    hidden = 0
    candidates: dict[str, ThreadRow] = {}
    referenced: set[int] = set()
    for comment in sorted(parsed, key=lambda c: (c.created_at, c.id)):
        repro = parse_repro(comment.body)
        if repro is None:
            hidden += 1
            continue
        row = ThreadRow(comment_id=comment.id, user=comment.user, created_at=comment.created_at, status="rejected")
        if isinstance(repro, str):
            rows.append(row.model_copy(update={"reason": repro}))
            continue
        row = _row_numbers(row, check, repro)
        if comment.updated_at != comment.created_at:
            rows.append(row.model_copy(update={"status": "edited", "reason": "edited after posting"}))
            continue
        if reason := validate_repro(check, repro):
            rows.append(row.model_copy(update={"reason": reason}))
            continue
        referenced.update(repro.seen)
        if engine is not None and repro.engine != engine:
            rows.append(row.model_copy(update={"status": "filtered", "reason": f"ran in {repro.engine}"}))
            continue
        if comment.user.lower() == author.lower():
            rows.append(row.model_copy(update={"status": "author"}))
            continue
        if previous := candidates.get(comment.user.lower()):
            rows.append(previous.model_copy(update={"status": "superseded", "reason": "a later reproduction counts"}))
        candidates[comment.user.lower()] = row.model_copy(update={"status": "counted"})
    rows += candidates.values()
    rows.sort(key=lambda r: (r.created_at, r.comment_id))
    counted = list(candidates.values())
    loaded = len(parsed)
    total = max(total or loaded, loaded)
    partial = total > loaded
    ids = {c.id for c in parsed}
    newest = max(ids, default=0)
    removed = len({i for i in referenced if i not in ids and (not partial or i <= newest)})
    stats = TrustStats(rows=rows, hidden=hidden, people=len(counted), partial=partial, loaded=loaded, total=total,
                       removed=removed)  # fmt: skip
    if not counted:
        return stats
    passed = sum(r.baseline_passed for r in counted)
    trials = sum(r.baseline_trials for r in counted)
    stats = stats.model_copy(update={"passed": passed, "trials": trials, "rate": passed / trials if trials else None})
    if len(counted) >= 2:
        low, high = wilson(passed, trials)
        above = len(counted) >= 3 and not partial and check.claim.result.pass_rate > high
        stats = stats.model_copy(update={"low": low, "high": high, "above_interval": above})
    return stats


def _row_numbers(row: ThreadRow, check: ClaimCheck, repro: Repro) -> ThreadRow:
    update: dict[str, Any] = {
        "engine": repro.engine,
        "baseline_passed": repro.baseline.passed,
        "baseline_trials": repro.baseline.trials,
        "baseline_cost_usd_per_task": repro.baseline.cost_usd_per_task,
    }
    if repro.variant is not None:
        changed = [r for r, spec in repro.variant.setup.roles.items() if check.claim.setup.roles.get(r) != spec]
        if changed:
            role = changed[0]
            update |= {"variant_role": role, "variant_model": repro.variant.setup.roles[role].model}
        else:
            update |= {"variant_role": "decisions", "variant_model": str((repro.variant.setup.decisions or {}).get(
                "policy"))}  # fmt: skip
        update |= {"variant_passed": repro.variant.passed,
                   "variant_cost_usd_per_task": repro.variant.cost_usd_per_task}  # fmt: skip
    return row.model_copy(update=update)
