"""Adversarial sandbox checks shared across every locally available execution backend."""

from __future__ import annotations

import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from llm_arena.adapters.server.safe_files import MAX_ARTIFACT_BYTES, MAX_ARTIFACT_TOTAL_BYTES
from llm_arena.adapters.server.subprocess_sandbox import (
    MAX_STREAM_BYTES,
    DockerSandbox,
    SubprocessSandbox,
    docker_ready,
)
from llm_arena.runner.ports import Runtime


@pytest.fixture(
    params=[
        pytest.param("process", id="unsafe-process"),
        pytest.param(
            "docker",
            id="docker",
            marks=pytest.mark.skipif(docker_ready() is not None, reason=f"Docker unavailable: {docker_ready()}"),
        ),
    ]
)
def sandbox(request: pytest.FixtureRequest) -> Iterator[SubprocessSandbox]:
    yield DockerSandbox() if request.param == "docker" else SubprocessSandbox()


async def test_all_backends_reject_escaping_inputs_and_never_collect_symlinks(
    sandbox: SubprocessSandbox,
) -> None:
    with pytest.raises(ValueError, match="invalid sandbox file name"):
        await sandbox.run("pass", files={"../escape": "no"})
    result = await sandbox.run("import os\nos.symlink('/etc/passwd', 'leak.txt')", collect=("leak.txt",))
    assert result.ok and result.files == {}
    assert result.omitted == {"leak.txt": "symlinks are not collected"}


async def test_all_backends_enforce_artifact_and_output_caps(sandbox: SubprocessSandbox) -> None:
    artifact = await sandbox.run(
        f"open('large.bin', 'wb').truncate({MAX_ARTIFACT_BYTES + 1})",
        collect=("large.bin",),
    )
    assert artifact.files == {}
    assert artifact.omitted == {"large.bin": f"file exceeds {MAX_ARTIFACT_BYTES} bytes"}

    output = await sandbox.run(f"print('x' * {MAX_STREAM_BYTES + 1})", timeout_s=10)
    assert output.output_truncated and not output.ok
    assert len(output.stdout.encode()) <= 8000 + len("\n…[output truncated]".encode())


async def test_all_backends_remove_their_temporary_work_directory(sandbox: SubprocessSandbox) -> None:
    root = Path(tempfile.gettempdir())
    before = set(root.glob("arena-sbx-*"))
    result = await sandbox.run("open('canary.txt', 'w').write('temporary')")
    after = set(root.glob("arena-sbx-*"))
    assert result.ok and after == before


async def test_unsafe_process_is_truthfully_labelled_and_can_read_a_test_owned_canary(tmp_path: Path) -> None:
    canary = tmp_path / "owned-canary.txt"
    canary.write_text("TEST-OWNED-CANARY", encoding="utf-8")
    sandbox = SubprocessSandbox()
    result = await sandbox.run(f"print(open({str(canary)!r}).read())")
    execution = Runtime(client_factory=lambda _: None, sandbox=sandbox).execution_environment()  # type: ignore[arg-type]
    assert result.stdout.strip() == "TEST-OWNED-CANARY"
    assert execution["backend"] == "unsafe-process" and execution["isolation"] == "process"


@pytest.mark.skipif(docker_ready() is not None, reason=f"Docker unavailable: {docker_ready()}")
async def test_docker_cannot_reach_host_files_or_write_outside_work(tmp_path: Path) -> None:
    canary = tmp_path / "host-only.txt"
    canary.write_text("HOST-ONLY", encoding="utf-8")
    code = (
        f"import os\nprint(os.path.exists({str(canary)!r}))\n"
        "try:\n open('/arena-escape', 'w').write('no')\n print('wrote')\n"
        "except OSError:\n print('blocked')\n"
    )
    result = await DockerSandbox().run(code)
    assert result.ok and result.stdout.split() == ["False", "blocked"]
    assert not Path("/arena-escape").exists()


@pytest.mark.skipif(docker_ready() is not None, reason=f"Docker unavailable: {docker_ready()}")
async def test_docker_cannot_reach_loopback_or_test_net() -> None:
    with loopback_listener() as (listener, port):
        code = (
            "import socket\n"
            f"targets = [('127.0.0.1', {port}), ('192.0.2.1', 80)]\n"
            "for target in targets:\n"
            " try:\n  socket.create_connection(target, timeout=0.3)\n  print('connected')\n"
            " except OSError:\n  print('blocked')\n"
        )
        result = await DockerSandbox().run(code, timeout_s=5)
        listener.settimeout(0.2)
        with pytest.raises(TimeoutError):
            listener.accept()
    assert result.ok and result.stdout.split() == ["blocked", "blocked"]


@pytest.mark.skipif(docker_ready() is not None, reason=f"Docker unavailable: {docker_ready()}")
async def test_docker_does_not_inherit_secrets_or_retain_children(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_ADVERSARIAL_SECRET", "must-not-cross")
    sandbox = DockerSandbox()
    result = await sandbox.run(
        "import os, subprocess, sys\n"
        "print('ARENA_ADVERSARIAL_SECRET' in os.environ)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])"
    )
    assert result.ok and result.stdout.strip() == "False"
    running = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"ancestor={sandbox.image}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert running.stdout.strip() == ""


@pytest.mark.skipif(docker_ready() is not None, reason=f"Docker unavailable: {docker_ready()}")
async def test_docker_enforces_total_artifact_cap() -> None:
    each = MAX_ARTIFACT_BYTES
    result = await DockerSandbox().run(
        f"for n in range(5):\n open(f'{{n}}.bin', 'wb').truncate({each})",
        collect=("*.bin",),
    )
    assert sum(map(len, result.files.values())) <= MAX_ARTIFACT_TOTAL_BYTES
    assert any("execution artifacts exceed" in reason for reason in result.omitted.values())


class loopback_listener:
    def __enter__(self) -> tuple[socket.socket, int]:
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        return self.socket, int(self.socket.getsockname()[1])

    def __exit__(self, *args: object) -> None:
        self.socket.close()
