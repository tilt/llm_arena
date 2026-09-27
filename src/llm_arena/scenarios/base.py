"""Scenario contract: tasks + a pipeline over role-bound models + step and end-to-end evaluators.

Benchmarks implement the same contract (one `model` role), so the runner, store and report
treat a GSM8K subset and a multi-agent pipeline alike.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

from llm_arena.core.errors import CapabilityError, ConfigError
from llm_arena.core.trace import Trace
from llm_arena.decisions.config import DecisionSetup
from llm_arena.eval.base import Evaluator, Task, TrialOutput
from llm_arena.llm.spec import ModelSpec
from llm_arena.mocks.search import SearchBackend
from llm_arena.patterns.roles import RoleModels
from llm_arena.sandbox.base import Sandbox
from llm_arena.scenarios.manifest import (
    EVALUATION_LINKS,
    PATTERN_LINKS,
    ParamManifest,
    Requirement,
    RoleManifest,
    ScenarioManifest,
    param_type,
)

Capability = Literal["tools", "vision", "json_schema"]


def work_dir() -> Path:
    """Scratch space for generated fixtures (e.g. the seeded SQLite DB). Works in Pyodide's in-memory FS too."""
    path = Path(os.getenv("ARENA_WORK_DIR") or Path(tempfile.gettempdir()) / "llm_arena")
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class RoleRequirement:
    name: str
    description: str
    needs: frozenset[Capability] = frozenset()
    fallback: str | None = None  # optional role: reuse another role's model when unbound


@dataclass
class RunContext:
    """Per-trial facts a pipeline may need besides its models."""

    trace: Trace
    params: dict[str, Any]
    live: bool = False
    seed: int = 0
    sandbox: Sandbox | None = None  # runtime-provided: subprocess/Docker on the server, a worker in the browser
    live_search: Callable[[str], SearchBackend] | None = None  # backend name -> live search (server, --live)
    decisions: DecisionSetup | None = None  # the config's control policy; None: the agent decides everything
    scratch: dict[str, Any] = field(default_factory=dict)

    def require_sandbox(self) -> Sandbox:
        if self.sandbox is None:
            raise RuntimeError("this scenario executes code and needs a sandbox, but the runtime provides none")
        return self.sandbox


class Scenario(ABC):
    name: ClassVar[str]
    pattern: ClassVar[str]
    description: ClassVar[str]
    roles: ClassVar[list[RoleRequirement]]
    default_params: ClassVar[dict[str, Any]] = {}
    # All of these e2e/step score names must pass for the trial to count as passed —
    # safety and quality together, as the agent-evaluation page recommends.
    pass_criteria: ClassVar[list[str]]
    open_ended: ClassVar[bool] = False  # eligible for pairwise arena battles
    pairwise_criteria: ClassVar[str] = ""
    # Manifest metadata for UIs and other runtimes.
    title: ClassVar[str] = ""
    kind: ClassVar[Literal["pattern", "benchmark"]] = "pattern"
    requires: ClassVar[frozenset[Requirement]] = frozenset()
    param_choices: ClassVar[dict[str, list[Any]]] = {}
    tokens_per_trial: ClassVar[int] = 3000  # rough prompt+completion estimate for cost previews
    supports_decisions: ClassVar[bool] = False  # accepts a control policy (PipelineConfig.decisions)

    @abstractmethod
    def load_tasks(self) -> list[Task]: ...

    @abstractmethod
    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput: ...

    @abstractmethod
    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]: ...

    def fixtures(self) -> dict[str, Any]:
        """Scenario data as files for other runtimes: name -> str (text) or JSON-able value.

        Includes seeded environments, tool schemas and rubrics; prompts are exported through the
        conformance vectors (the exact requests each role receives).
        """
        return {}

    def task_count(self) -> int:
        return len(self.load_tasks())

    def manifest(self) -> ScenarioManifest:
        return ScenarioManifest(
            id=self.name,
            title=self.title or self.name.replace("_", " ").capitalize(),
            pattern=self.pattern,
            description=self.description,
            kind=self.kind,
            roles=[
                RoleManifest(name=r.name, description=r.description, needs=sorted(r.needs), fallback=r.fallback)
                for r in self.roles
            ],
            params=[
                ParamManifest(name=key, type=param_type(value), default=value, choices=self.param_choices.get(key))
                for key, value in self.default_params.items()
            ],
            pass_criteria=list(self.pass_criteria),
            requires=sorted(self.requires),
            open_ended=self.open_ended,
            supports_decisions=self.supports_decisions,
            tasks=self.task_count(),
            wiki=list({link.url: link for link in [*PATTERN_LINKS.get(self.pattern, []), *EVALUATION_LINKS]}.values()),
        )

    def params(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        unknown = set(overrides or {}) - set(self.default_params)
        if unknown:
            raise ConfigError(f"{self.name}: unknown params {sorted(unknown)}; known: {sorted(self.default_params)}")
        return {**self.default_params, **(overrides or {})}

    def check_roles(self, bindings: dict[str, ModelSpec]) -> dict[str, ModelSpec]:
        """Validate a role → model binding and fill optional roles from their fallbacks."""
        resolved = dict(bindings)
        known = {requirement.name for requirement in self.roles}
        if extra := set(bindings) - known:
            raise ConfigError(f"{self.name}: unknown roles {sorted(extra)}; roles are {sorted(known)}")
        for requirement in self.roles:
            spec = resolved.get(requirement.name)
            if spec is None and requirement.fallback and requirement.fallback in resolved:
                spec = resolved[requirement.name] = resolved[requirement.fallback]
            if spec is None:
                raise ConfigError(f"{self.name}: role {requirement.name!r} ({requirement.description}) needs a model")
            missing = [need for need in requirement.needs if not getattr(spec.capabilities, need)]
            if missing:
                raise CapabilityError(
                    f"{self.name}: role {requirement.name!r} needs {missing}, which {spec.name} lacks"
                )
        return resolved


def load_jsonl_tasks(path: Path) -> list[Task]:
    return [
        Task.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


SCENARIOS: dict[str, type[Scenario]] = {}


def register(cls: type[Scenario]) -> type[Scenario]:
    if cls.name in SCENARIOS:
        raise ValueError(f"duplicate scenario {cls.name!r}")
    SCENARIOS[cls.name] = cls
    return cls


def get_scenario(name: str) -> Scenario:
    import llm_arena.benchmarks  # noqa: F401  (import registers benchmark scenarios)
    import llm_arena.scenarios.catalog  # noqa: F401  (import registers pattern scenarios)

    if name not in SCENARIOS:
        raise ConfigError(f"unknown scenario {name!r}; available: {sorted(SCENARIOS)}")
    return SCENARIOS[name]()
