"""Model-written code runs in Docker when possible; anything less is chosen explicitly or announced."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_arena.adapters.server import runtime
from llm_arena.adapters.server.subprocess_sandbox import DockerSandbox, SubprocessSandbox
from llm_arena.core.errors import ConfigError


def test_auto_uses_docker_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "docker_ready", lambda: None)
    sandbox, warning = runtime.choose_sandbox("auto")
    assert isinstance(sandbox, DockerSandbox) and sandbox.isolation == "container" and warning is None


def test_auto_fails_closed_with_a_hint_and_docker_mode_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "docker_ready", lambda: "the Docker daemon is not running")
    sandbox, warning = runtime.choose_sandbox("auto")
    assert sandbox is None
    assert warning and "unsafe-process" in warning and "make sandbox-image" in warning
    with pytest.raises(ConfigError, match="daemon is not running"):
        runtime.choose_sandbox("docker")
    unsafe, warning = runtime.choose_sandbox("unsafe-process")
    assert type(unsafe) is SubprocessSandbox and warning and "without isolation" in warning
    assert "deprecated" in (runtime.choose_sandbox("subprocess")[1] or "")


def test_docker_containers_are_locked_down(tmp_path: Path) -> None:
    command = DockerSandbox()._command(tmp_path)
    for flag in (
        ["--network", "none"],
        ["--read-only", "--tmpfs"],
        ["--cap-drop", "ALL"],
        ["--security-opt", "no-new-privileges"],
        ["--pids-limit", "256"],
    ):
        at = command.index(flag[0])
        assert command[at + 1] == flag[1]
    assert "llm-arena-sandbox:latest" in command


def test_containers_run_as_the_calling_user(tmp_path: Path) -> None:
    import os

    command = DockerSandbox()._command(tmp_path)
    assert command[command.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
