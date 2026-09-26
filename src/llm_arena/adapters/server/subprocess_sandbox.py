"""Server sandboxes: model-written Python in a subprocess (temp dir, timeout, rlimits, clean env) or Docker.

The subprocess sandbox is isolation against accidents (infinite loops, stray files, leaked API
keys), not against a determined attacker: there is no network namespace on macOS. Use
DockerSandbox (same interface) for untrusted models or when network isolation matters.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from llm_arena.sandbox.base import ExecResult, clip


class SubprocessSandbox:
    """Executes with the arena's own interpreter so matplotlib/pandas are available to the code."""

    def __init__(self, python: str = sys.executable, memory_mb: int = 2048) -> None:
        self.python = python
        self.memory_mb = memory_mb

    async def run(
        self,
        code: str,
        *,
        files: dict[str, bytes | str] | None = None,
        collect: tuple[str, ...] = (),
        timeout_s: float = 30.0,
    ) -> ExecResult:
        with tempfile.TemporaryDirectory(prefix="arena-sbx-") as workdir:
            root = Path(workdir)
            for relative, content in (files or {}).items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            (root / "main.py").write_text(code, encoding="utf-8")
            loop = asyncio.get_running_loop()
            started = loop.time()
            process = await asyncio.create_subprocess_exec(
                *self._command(root),
                cwd=root,
                env=self._env(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=self._limits(timeout_s),
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
                timed_out = False
            except TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                timed_out = True
            result = ExecResult(
                stdout=clip(stdout.decode("utf-8", "replace")),
                stderr=clip(stderr.decode("utf-8", "replace")),
                returncode=process.returncode if process.returncode is not None else -1,
                timed_out=timed_out,
                duration_s=loop.time() - started,
            )
            result.files = {
                str(path.relative_to(root)): path.read_bytes()
                for pattern in collect
                for path in root.glob(pattern)
                if path.is_file()
            }
            return result

    def _command(self, workdir: Path) -> list[str]:
        # -E: ignore PYTHON* env vars; -s: no user site-packages. Not -I, which would also drop the
        # script directory from sys.path and break `from api import *` for CodeAct environments.
        return [self.python, "-E", "-s", "main.py"]

    def _env(self, workdir: Path) -> dict[str, str]:
        return _clean_env(workdir)

    def _limits(self, timeout_s: float) -> Callable[[], None]:
        memory_bytes = self.memory_mb * 1024 * 1024
        cpu_seconds = int(timeout_s) + 1

        def apply() -> None:
            # Imported here: `resource` is POSIX-only and absent in Pyodide, where the package must still import.
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            with contextlib.suppress(ValueError, OSError):  # macOS does not enforce RLIMIT_AS; Linux does
                resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))

        return apply


def _clean_env(workdir: Path) -> dict[str, str]:
    """Only what Python needs — in particular no API keys reach model-written code."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workdir),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(workdir / ".mpl"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }


class DockerSandbox(SubprocessSandbox):
    """Same interface inside `docker run --network none`: for untrusted code or when isolation matters.

    The image needs whatever the scenario's code imports (e.g. matplotlib for charts).
    """

    def __init__(self, image: str = "python:3.12-slim", memory_mb: int = 2048) -> None:
        super().__init__(python="python", memory_mb=memory_mb)
        self.image = image

    def _command(self, workdir: Path) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            f"{self.memory_mb}m",
            "-e",
            "MPLBACKEND=Agg",
            "-v",
            f"{workdir}:/work",
            "-w",
            "/work",
            self.image,
            "python",
            "main.py",
        ]

    def _env(self, workdir: Path) -> dict[str, str]:
        return {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/")}
