"""The checked-in contracts (schemas, scenario data, conformance vectors) must match the engine.

If this fails after an intended change, regenerate with `uv run arena contracts` and review the diff:
it is exactly what other runtimes (web UI types, Pyodide build, a TypeScript port) will see change.
"""

from __future__ import annotations

from pathlib import Path

from llm_arena.adapters.server.subprocess_sandbox import SubprocessSandbox
from llm_arena.contracts import stale_files

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


async def test_contracts_are_up_to_date() -> None:
    assert await stale_files(CONTRACTS, SubprocessSandbox()) == []
