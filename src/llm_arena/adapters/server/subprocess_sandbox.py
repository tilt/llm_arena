"""Server sandboxes: model-written Python in a subprocess (temp dir, timeout, rlimits, clean env) or Docker.

The subprocess sandbox is isolation against accidents (infinite loops, stray files, leaked API
keys), not against a determined attacker: there is no network namespace on macOS. Use
DockerSandbox (same interface) for untrusted models or when network isolation matters.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from llm_arena.sandbox.base import ExecResult, clip


class SubprocessSandbox:
    """Local subprocess with a temp dir, a clean environment, CPU/memory limits and a timeout.

    This guards against accidents (runaway loops, stray files), not against hostile code: the process runs as your
    user with network access. Use DockerSandbox for isolation.
    """

    isolation = "process"

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
                await self._terminate(process, root)
                stdout, stderr = await process.communicate()
                timed_out = True
            except asyncio.CancelledError:  # e.g. the trial timed out around this step: never leave code running
                await self._terminate(process, root)
                raise
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

    async def _terminate(self, process: asyncio.subprocess.Process, workdir: Path) -> None:
        if process.returncode is None:
            process.kill()

    def _command(self, workdir: Path) -> list[str]:
        # -E: ignore PYTHON* env vars; -s: no user site-packages. Not -I, which would also drop the
        # script directory from sys.path and break `from api import *` for CodeAct environments.
        return [self.python, "-E", "-s", "main.py"]

    def _env(self, workdir: Path) -> dict[str, str]:
        return _clean_env(workdir)

    def _limits(self, timeout_s: float) -> Callable[[], None] | None:
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


SANDBOX_IMAGE = "llm-arena-sandbox:latest"  # built by `make sandbox-image` (docker/sandbox.Dockerfile)


def docker_ready(image: str = SANDBOX_IMAGE) -> str | None:
    """None when Docker runs and the sandbox image exists; otherwise why not (for the warning)."""
    try:
        result = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=5, check=False)
    except FileNotFoundError:
        return "Docker is not installed"
    except subprocess.TimeoutExpired:
        return "Docker did not answer"
    if result.returncode == 0:
        return None
    if b"Cannot connect" in result.stderr or b"daemon" in result.stderr:
        return "the Docker daemon is not running"
    return f"the sandbox image {image} is missing (make sandbox-image)"


class DockerSandbox(SubprocessSandbox):
    """Same interface inside `docker run --network none`: for untrusted code or when isolation matters.

    The image needs whatever the scenario's code imports (e.g. matplotlib for charts).
    """

    isolation = "container"

    def __init__(self, image: str = SANDBOX_IMAGE, memory_mb: int = 2048) -> None:
        super().__init__(python="python", memory_mb=memory_mb)
        self.image = image

    @staticmethod
    def _name(workdir: Path) -> str:
        return f"arena-{workdir.name}"  # the temp dir is unique per run, so is the container name

    async def _terminate(self, process: asyncio.subprocess.Process, workdir: Path) -> None:
        # Killing the `docker run` client does not stop the container: kill the container itself.
        killer = await asyncio.create_subprocess_exec(
            "docker", "kill", self._name(workdir), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await killer.wait()
        await super()._terminate(process, workdir)

    def _limits(self, timeout_s: float) -> Callable[[], None] | None:
        return None  # the container has its own CPU, memory and process limits; the docker client needs none

    def _command(self, workdir: Path) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--name",
            self._name(workdir),
            "--network",
            "none",
            "--memory",
            f"{self.memory_mb}m",
            "--cpus",
            "1",
            "--pids-limit",
            "256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
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
