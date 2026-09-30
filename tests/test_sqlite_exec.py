"""Model-written SQL may read the scenario's database and nothing else."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from llm_arena.mocks.sqlite_exec import NOT_ALLOWED, run_query


@pytest.fixture
def dbs(tmp_path: Path) -> tuple[Path, Path]:
    main, other = tmp_path / "shop.db", tmp_path / "other.db"
    with sqlite3.connect(main) as db:
        db.executescript(
            "CREATE TABLE bikes (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO bikes VALUES (1, 'a'), (2, 'b');"
        )
    with sqlite3.connect(other) as db:
        db.executescript("CREATE TABLE secret (v TEXT); INSERT INTO secret VALUES ('host data');")
    return main, other


def test_reading_queries_work(dbs: tuple[Path, Path]) -> None:
    main, _ = dbs
    assert run_query(main, "SELECT name FROM bikes ORDER BY id").rows == [("a",), ("b",)]
    recursive = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 3) SELECT count(*) FROM n"
    assert run_query(main, recursive).rows == [(3,)]
    assert run_query(main, "SELECT upper(name), length(name) FROM bikes LIMIT 1").rows == [("A", 1)]
    assert [r[1] for r in run_query(main, "PRAGMA table_info(bikes)").rows] == ["id", "name"]
    assert run_query(main, "SELECT name FROM sqlite_master WHERE type = 'table'").rows == [("bikes",)]


@pytest.mark.parametrize("sql", [
    "ATTACH DATABASE '{other}' AS o",
    "ATTACH DATABASE '{created}' AS n",
    "INSERT INTO bikes VALUES (3, 'c')",
    "DELETE FROM bikes",
    "CREATE TABLE x (y)",
    "PRAGMA journal_mode = WAL",
    "SELECT load_extension('x')",
])  # fmt: skip
def test_everything_else_is_refused(dbs: tuple[Path, Path], tmp_path: Path, sql: str) -> None:
    main, other = dbs
    result = run_query(main, sql.format(other=other, created=tmp_path / "created.db"))
    assert not result.ok
    assert not (tmp_path / "created.db").exists()
    assert run_query(main, "SELECT count(*) FROM bikes").rows == [(2,)]


def test_other_files_stay_out_of_reach(dbs: tuple[Path, Path]) -> None:
    main, other = dbs
    result = run_query(main, f"ATTACH DATABASE '{other}' AS o")
    assert result.error and NOT_ALLOWED in result.error
