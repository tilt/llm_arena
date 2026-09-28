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
    roles = {role: {field: getattr(spec, field) for field in SPEC_FIELDS} for role, spec in sorted(bindings.items())}
    return {"roles": roles, "params": params, "decisions": decisions}


def fingerprint(setup: dict[str, Any]) -> str:
    return _digest(setup)


def task_fingerprint(task: Task) -> str:
    return _digest(task.model_dump(mode="json"), 8)
