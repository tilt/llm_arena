"""The sandbox reports how the Docker daemon runs (containers run as the user either way)."""

from __future__ import annotations

import subprocess

import pytest

from llm_arena.adapters.server import subprocess_sandbox
from llm_arena.adapters.server.subprocess_sandbox import docker_daemon

LINUX_ROOTFUL = 'Ubuntu 24.04.1 LTS|["name=apparmor","name=seccomp,profile=builtin","name=cgroupns"]'
LINUX_ROOTLESS = 'Ubuntu 24.04.1 LTS|["name=seccomp,profile=builtin","name=rootless","name=cgroupns"]'
DESKTOP = 'Docker Desktop|["name=seccomp,profile=builtin","name=cgroupns"]'


@pytest.mark.parametrize(("platform", "stdout", "code", "expected"), [
    ("linux", LINUX_ROOTFUL, 0, "root"),
    ("linux", LINUX_ROOTLESS, 0, "rootless"),
    ("linux", DESKTOP, 0, "vm"),          # Docker Desktop on Linux runs a VM too
    ("darwin", LINUX_ROOTFUL, 0, "vm"),   # e.g. Colima or OrbStack: on macOS every daemon is in a VM
    ("linux", "", 1, ""),                 # daemon not running
    ("linux", "podman 5", 0, ""),         # an answer we do not understand: say nothing
])  # fmt: skip
def test_daemon_modes(monkeypatch: pytest.MonkeyPatch, platform: str, stdout: str, code: int, expected: str) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, code, stdout=stdout + "\n", stderr="")

    monkeypatch.setattr(subprocess_sandbox.subprocess, "run", run)
    monkeypatch.setattr(subprocess_sandbox.sys, "platform", platform)
    assert docker_daemon() == expected


def test_no_docker_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess_sandbox.subprocess, "run", missing)
    assert docker_daemon() == ""  # nothing raised
