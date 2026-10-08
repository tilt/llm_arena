"""What makes two trials comparable across runs: the same setup and the same task version.

A config's *name* is a label; its fingerprint is what it actually ran: each role's model and call
settings, the scenario parameters and the control policy. Scenarios carry a manual `version` that
is bumped when prompts or evaluators change, and each task a hash of its content, so a leaderboard
never pools results from different task sets or grading rules.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from llm_arena.eval.base import Task
from llm_arena.llm.spec import ModelSpec

# Call settings that change results. Endpoints, keys, timeouts and prices do not.
SPEC_FIELDS = ("provider", "model", "backend", "tool_mode", "temperature", "reasoning_effort", "max_tokens")


def _digest(value: Any, length: int = 12) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(canonical.encode()).hexdigest()[:length]


def setup_of(
    bindings: dict[str, ModelSpec], params: dict[str, Any], decisions: dict[str, Any] | None
) -> dict[str, Any]:
    roles = {role: _role_setup(spec) for role, spec in sorted(bindings.items())}
    return {"roles": roles, "params": params, "decisions": decisions}


def _role_setup(spec: ModelSpec) -> dict[str, Any]:
    setup = {field: getattr(spec, field) for field in SPEC_FIELDS}
    # The same model id on two named endpoints may be served differently (quantization, context, engine), so the
    # endpoint is part of the setup. Added only when set, so every earlier fingerprint stays valid.
    if spec.endpoint:
        setup["endpoint"] = spec.endpoint
        # The keyed hash of its URL (`Endpoint.identity`): the same name pointed at another server is another setup.
        setup["endpoint_identity"] = spec.endpoint_identity
    return setup


def fingerprint(setup: dict[str, Any]) -> str:
    return _digest(setup)


def resume_key(setup_fingerprint: str, scenario_version: str, task_fp: str, seed: int) -> str:
    """Everything a finished trial's result depends on besides the models' randomness: a resumed run may skip a
    trial only when this matches."""
    return _digest([setup_fingerprint, scenario_version, task_fp, seed], 16)


def task_fingerprint(task: Task) -> str:
    return _digest(task.model_dump(mode="json"), 8)
