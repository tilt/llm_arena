"""Ports the runner depends on: run storage and the runtime environment (clients, catalog, sandbox, search).

Server implementations live in `adapters.server`; the browser engine supplies its own. The runner
itself never imports DuckDB, httpx, SDKs or subprocess.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from llm_arena.core.trace import Trace
from llm_arena.eval.base import Score
from llm_arena.llm.catalog import Catalog
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.mocks.search import SearchBackend
from llm_arena.sandbox.base import Sandbox

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


@dataclass
class RunData:
    """Everything a report needs, as plain rows (the same shape every store returns)."""

    run: dict[str, Any]
    trials: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    battles: list[dict[str, Any]] = field(default_factory=list)


class RunStore(Protocol):
    def start_run(self, run_id: str, name: str, config_json: str) -> None: ...

    def completed_trials(self) -> set[str]: ...

    def save_trial(
        self, run_id: str, record: TrialRecord, scores: list[Score], trace: Trace, extra: dict[str, Any]
    ) -> None: ...

    def finals_for_battles(self, scenario: str) -> list[tuple[str, str, str]]: ...

    def save_battle(self, scenario: str, task_id: str, a: str, b: str, winner: str, rationale: str) -> None: ...

    def has_battle(self, scenario: str, task_id: str, a: str, b: str) -> bool: ...

    def load_run(self) -> RunData: ...

    def load_trace(self, trial_id: str) -> dict[str, Any] | None: ...


@dataclass
class Runtime:
    """What a run needs from its environment. `name` is reported to the UI (server | browser)."""

    client_factory: ClientFactory
    discover: Callable[[], Awaitable[Catalog]] | None = None
    sandbox: Sandbox | None = None
    live_search: Callable[[str], SearchBackend] | None = None
    name: str = "server"
