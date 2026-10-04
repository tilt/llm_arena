from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from llm_arena.runner.run import new_run_id, valid_run_id
from llm_arena.server.app import _require_run


@pytest.mark.parametrize("name", ["simple", "with spaces", "ümlaut / path", "...", "x" * 500])
def test_generated_run_ids_are_strict_slugs(name: str) -> None:
    run_id = new_run_id(name)
    assert valid_run_id(run_id)
    assert len(run_id) <= 121


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        ".hidden",
        "../escape",
        "a/b",
        "a\\b",
        "space name",
        "nul\0name",
        "é",
        "x" * 122,
        "CON",
        "aux.txt",
        "trailing.",
        "percent%2fescape",
        "line\nbreak",
    ],
)
def test_new_run_id_validator_rejects_unsafe_or_nonportable_values(run_id: str) -> None:
    assert not valid_run_id(run_id)


def test_legacy_read_requires_a_real_direct_child(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy run ü"
    legacy.mkdir()
    (legacy / "arena.duckdb").touch()
    _require_run(tmp_path, legacy.name)
    with pytest.raises(HTTPException):
        _require_run(tmp_path, legacy.name, mutation=True)

    outside = tmp_path.parent / "outside-run"
    outside.mkdir(exist_ok=True)
    (outside / "arena.duckdb").touch()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(HTTPException):
        _require_run(tmp_path, "linked")
