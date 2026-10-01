"""Security invariants shared by the local-process and Docker sandbox implementations."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_arena.adapters.server.safe_files import MAX_ARTIFACT_BYTES
from llm_arena.adapters.server.subprocess_sandbox import MAX_STREAM_BYTES, SubprocessSandbox


@pytest.fixture
def sandbox() -> SubprocessSandbox:
    return SubprocessSandbox()


@pytest.mark.parametrize(
    "name",
    [
        "",
        "/absolute",
        "../outside",
        "dir/../outside",
        "dir//file",
        "dir/./file",
        "back\\slash",
        "C:/drive",
        "nul\0name",
    ],
)
async def test_input_names_reject_ambiguous_or_escaping_paths(sandbox: SubprocessSandbox, name: str) -> None:
    with pytest.raises(ValueError, match="invalid sandbox file name"):
        await sandbox.run("pass", files={name: "content"})


async def test_regular_nested_inputs_and_artifacts_still_work(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(
        "from pathlib import Path\nPath('out').mkdir()\nPath('out/result.txt').write_text(Path('in/data.txt').read_text())",
        files={"in/data.txt": "hello"},
        collect=("out/*",),
    )
    assert result.ok
    assert result.files == {"out/result.txt": b"hello"}
    assert result.omitted == {}


async def test_artifact_collection_never_follows_file_or_parent_symlinks(
    sandbox: SubprocessSandbox, tmp_path: Path
) -> None:
    canary = tmp_path / "host-canary.txt"
    canary.write_text("HOST-CANARY", encoding="utf-8")
    code = f"import os\nos.symlink({str(canary)!r}, 'direct.txt')\nos.symlink({str(tmp_path)!r}, 'linked-dir')\n"
    result = await sandbox.run(code, collect=("direct.txt", "linked-dir/*"))
    assert result.ok
    assert result.files == {}
    assert set(result.omitted) == {"direct.txt", "linked-dir/host-canary.txt"}
    assert all(b"HOST-CANARY" not in value for value in result.files.values())


async def test_artifact_file_cap_is_reported_without_reading_the_file(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(
        f"open('large.bin', 'wb').truncate({MAX_ARTIFACT_BYTES + 1})",
        collect=("large.bin",),
    )
    assert result.ok
    assert result.files == {}
    assert result.omitted == {"large.bin": f"file exceeds {MAX_ARTIFACT_BYTES} bytes"}


async def test_output_cap_terminates_execution_and_bounds_capture(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(f"print('x' * {MAX_STREAM_BYTES + 1})", timeout_s=10)
    assert result.output_truncated
    assert not result.ok
    assert len(result.stdout.encode()) <= 8000 + len("\n…[output truncated]".encode())
    assert "1048576-byte limit" in result.observation()


async def test_lingering_child_cannot_hold_output_pipes_open(sandbox: SubprocessSandbox) -> None:
    result = await sandbox.run(
        "import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
        timeout_s=3,
    )
    assert result.ok
