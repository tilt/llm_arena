"""Sandbox port: run model-written Python somewhere isolated and get stdout/stderr/files back.

Implementations: `adapters.server.subprocess_sandbox` (subprocess or Docker) and, in the browser,
a separate Pyodide worker that is terminated on timeout. Scenarios receive one via RunContext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

MAX_OUTPUT_CHARS = 8000


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    files: dict[str, bytes] = field(default_factory=dict)  # outputs matched by `collect`
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def observation(self) -> str:
        """What the model sees after running code."""
        if self.timed_out:
            return "Execution timed out."
        parts = [f"exit code {self.returncode}"]
        if self.stdout.strip():
            parts.append(f"stdout:\n{self.stdout.strip()}")
        if self.stderr.strip():
            parts.append(f"stderr:\n{self.stderr.strip()}")
        return "\n".join(parts)


class Sandbox(Protocol):
    async def run(
        self,
        code: str,
        *,
        files: dict[str, bytes | str] | None = None,
        collect: tuple[str, ...] = (),
        timeout_s: float = 30.0,
    ) -> ExecResult: ...


def clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n…[output truncated]"
