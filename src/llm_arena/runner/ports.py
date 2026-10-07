"""Ports the runner depends on: run storage and the runtime environment (clients, catalog, sandbox, search).

Server implementations live in `adapters.server`; the browser engine supplies its own. The runner
itself never imports DuckDB, httpx, SDKs or subprocess.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from llm_arena.core.artifacts import ArtifactRef
from llm_arena.core.trace import Trace
from llm_arena.decisions.config import ServiceFactory
from llm_arena.eval.base import Score
from llm_arena.llm.catalog import Catalog
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.mocks.search import SearchBackend
from llm_arena.sandbox.base import Sandbox

if TYPE_CHECKING:
    from llm_arena.runner.regrade import RegradedTrial
    from llm_arena.runner.rename import RenameRun

ClientFactory = Callable[[ModelSpec], LLMClient]


@dataclass
class TrialRecord:
    trial_id: str
    scenario: str
    pattern: str
    config: str
    task_id: str
    repeat: int
    status: str  # ok | error | timeout | budget
    passed: bool
    error: str | None
    final: str
    duration_s: float
    totals: dict[str, float]
    judge_cost_usd: float
    roles: dict[str, str]
    params: dict[str, Any]
    # Cross-run comparability (see runner/fingerprint.py)
    fingerprint: str = ""
    scenario_version: str = ""
    task_fp: str = ""
    setup: dict[str, Any] = field(default_factory=dict)
    resume_key: str = ""
    execution: dict[str, str] = field(default_factory=dict)
    # Partial credit (see eval/credit.py): share of the graded work done, and each pass criterion's credit/verdict.
    credit: float = 0.0
    criteria: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class RunData:
    """Everything a report needs, as plain rows (the same shape every store returns)."""

    run: dict[str, Any]
    trials: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    battles: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)  # one row per control decision × question


class RunStore(Protocol):
    def start_run(self, run_id: str, name: str, config_json: str, execution_json: str = "{}") -> None: ...

    def completed_trials(self) -> dict[str, str]:
        """Finished trials: trial id -> resume key ("" for runs recorded before resume keys existed)."""
        ...

    def save_trial(
        self, run_id: str, record: TrialRecord, scores: list[Score], trace: Trace, extra: dict[str, Any]
    ) -> None: ...

    def finals_for_battles(self, scenario: str) -> list[tuple[str, str, str]]: ...

    def save_battle(self, scenario: str, task_id: str, a: str, b: str, winner: str, rationale: str) -> None: ...

    def has_battle(self, scenario: str, task_id: str, a: str, b: str) -> bool: ...

    def load_run(self) -> RunData: ...

    def load_trace(self, trial_id: str) -> dict[str, Any] | None: ...

    def clear_artifacts(self, trial_id: str) -> None: ...

    def save_artifact(self, trial_id: str, name: str, data: bytes, media_type: str) -> ArtifactRef: ...

    def load_artifact(self, key: str) -> tuple[bytes, str] | None: ...

    def rename(self, request: RenameRun) -> None:
        """New run and setup names; ids stay (see runner/rename.py)."""
        ...

    def regrade(self, trials: list[RegradedTrial]) -> None:
        """Store new grading for finished trials: version, verdict, credit, scores and trace (see runner/regrade.py)."""
        ...


@dataclass
class Runtime:
    """What a run needs from its environment. `name` is reported to the UI (server | browser)."""

    client_factory: ClientFactory
    discover: Callable[[], Awaitable[Catalog]] | None = None
    sandbox: Sandbox | None = None
    sandbox_hint: str = ""
    live_search: Callable[[str], SearchBackend] | None = None
    decision_services: ServiceFactory | None = None  # Jev / Ollaya decision models; None where unreachable (browser)
    # service -> (status, models), for the UI; None where the services cannot be reached
    decision_status: Callable[[], Awaitable[dict[str, tuple[str, list[str]]]]] | None = None
    name: str = "server"

    def execution_environment(self) -> dict[str, str]:
        sandbox = self.sandbox
        display = getattr(sandbox, "isolation", "") if sandbox else ""
        isolation = "browser" if display == "browser worker" else display
        backend = {
            "container": "docker",
            "process": "unsafe-process",
            "browser": "browser-worker",
            "": "none",
        }.get(isolation, type(sandbox).__name__ if sandbox else "none")
        return {
            "backend": backend,
            "isolation": isolation,
            "daemon": str(getattr(sandbox, "daemon", "")) if sandbox else "",
            "image_id": str(getattr(sandbox, "image_id", "")) if sandbox else "",
            "sandbox_policy": "1",
            "browser_network": str(getattr(sandbox, "network_isolation", "")) if sandbox else "",
        }
