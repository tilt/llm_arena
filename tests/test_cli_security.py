from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from llm_arena.cli import app
from llm_arena.server.session import token_path


def test_ui_link_prints_persistent_fragment_without_starting_server(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()
    first = runner.invoke(app, ["ui", "--link", "--port", "9876"])
    assert first.exit_code == 0
    token = token_path().read_text().strip()
    assert first.stdout.strip() == f"http://127.0.0.1:9876/#token={token}"

    same = runner.invoke(app, ["ui", "--link", "--port", "9876"])
    assert same.exit_code == 0 and same.stdout == first.stdout
    rotated = runner.invoke(app, ["ui", "--link", "--new-token", "--port", "9876"])
    assert rotated.exit_code == 0
    assert rotated.stdout != first.stdout
