"""Export the language-neutral contracts: JSON Schemas, scenario data, conformance vectors.

`arena contracts export` writes them to `contracts/`; CI regenerates and diffs them, so the files a
web UI (TypeScript types) or another engine (Pyodide build, TypeScript port) rely on never drift
from the Python engine, which stays the single source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from llm_arena.api import (
    Candidate,
    CandidatesRequest,
    ClaimDraftRequest,
    ClaimExperimentRequest,
    CreateClaimGist,
    CreatedGist,
    EndpointView,
    GistClaim,
    GistComment,
    PostComment,
    ReproDraftRequest,
    RunListing,
    RunStartedResponse,
    RuntimeResponse,
    SaveEndpoint,
    SetKey,
    StartRun,
    ThreadRequest,
)
from llm_arena.claims import Claim, ClaimCheck, ClaimDraft, Repro, ReproDraft, Swap, TrustStats
from llm_arena.conformance import CASES, claim_vectors, needs_sandbox, record
from llm_arena.core.task import Task
from llm_arena.core.trace import Trace
from llm_arena.eval.base import Score
from llm_arena.llm.catalog import CatalogEntry
from llm_arena.llm.spec import ModelSpec
from llm_arena.report.leaderboard import Leaderboard
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import RunEvent
from llm_arena.runner.rename import RenameRun
from llm_arena.sandbox.base import Sandbox
from llm_arena.scenarios.base import SCENARIOS, get_scenario
from llm_arena.scenarios.brief import TaskView
from llm_arena.scenarios.manifest import ScenarioManifest
from llm_arena.service import Estimate, RunBundle, RuntimeInfo

SCHEMA_TYPES: dict[str, Any] = {
    "ModelSpec": ModelSpec,
    "CatalogEntry": CatalogEntry,
    "ScenarioManifest": ScenarioManifest,
    "ExperimentConfig": ExperimentConfig,
    "RunEvent": RunEvent,
    "Task": Task,
    "Score": Score,
    "Trace": Trace,
    "RunBundle": RunBundle,
    "Leaderboard": Leaderboard,
    "TaskView": TaskView,
    "RuntimeInfo": RuntimeInfo,
    "Estimate": Estimate,
    "StartRun": StartRun,
    "RenameRun": RenameRun,
    "RunStartedResponse": RunStartedResponse,
    "RunListing": RunListing,
    "RuntimeResponse": RuntimeResponse,
    "SetKey": SetKey,
    "SaveEndpoint": SaveEndpoint,
    "EndpointView": EndpointView,
    "Claim": Claim,
    "Repro": Repro,
    "ClaimCheck": ClaimCheck,
    "ClaimDraft": ClaimDraft,
    "ReproDraft": ReproDraft,
    "TrustStats": TrustStats,
    "Swap": Swap,
    "ClaimDraftRequest": ClaimDraftRequest,
    "ReproDraftRequest": ReproDraftRequest,
    "ClaimExperimentRequest": ClaimExperimentRequest,
    "CandidatesRequest": CandidatesRequest,
    "Candidate": Candidate,
    "ThreadRequest": ThreadRequest,
    "GistClaim": GistClaim,
    "GistComment": GistComment,
    "CreateClaimGist": CreateClaimGist,
    "CreatedGist": CreatedGist,
    "PostComment": PostComment,
}


def _dump(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"


async def build(sandbox: Sandbox | None) -> dict[str, str]:
    """All contract files as {relative path: content}. Deterministic, so CI can diff them."""
    files: dict[str, str] = {}
    for name, type_ in SCHEMA_TYPES.items():
        files[f"schemas/{name}.schema.json"] = _dump(TypeAdapter(type_).json_schema())
    get_scenario("email_assistant")  # registers every scenario
    for name in sorted(SCENARIOS):
        scenario = get_scenario(name)
        files[f"scenarios/{name}/manifest.json"] = _dump(scenario.manifest().model_dump())
        if scenario.kind == "pattern":  # benchmark items stay with their licensed upstream sources
            tasks = "".join(
                json.dumps(task.model_dump(), sort_keys=True, default=str) + "\n" for task in scenario.load_tasks()
            )
            files[f"scenarios/{name}/tasks.jsonl"] = tasks
        for filename, content in scenario.fixtures().items():
            files[f"scenarios/{name}/fixtures/{filename}"] = _dump(content)
    for case in CASES:
        if needs_sandbox(case) and sandbox is None:
            continue
        files[f"conformance/{case.id}.json"] = _dump(await record(case, sandbox))
    for name, vector in claim_vectors().items():
        files[f"conformance/{name}.json"] = _dump(vector)
    return files


async def export(out_dir: Path, sandbox: Sandbox | None) -> list[str]:
    """Write contracts to `out_dir`, removing stale files; returns the written paths."""
    files = await build(sandbox)
    for stale in out_dir.rglob("*") if out_dir.exists() else []:
        if stale.is_file() and str(stale.relative_to(out_dir)) not in files:
            stale.unlink()
    for relative, content in files.items():
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return sorted(files)


async def stale_files(out_dir: Path, sandbox: Sandbox | None) -> list[str]:
    """Paths whose checked-in content differs from what the engine generates now."""
    files = await build(sandbox)
    existing = {str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file()} if out_dir.exists() else set()
    changed = [
        path
        for path, content in files.items()
        if not (out_dir / path).exists() or (out_dir / path).read_text(encoding="utf-8") != content
    ]
    return sorted(set(changed) | (existing - set(files)))
