"""Read-only, time-bounded SQL execution for model-written queries."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def preview(self, max_rows: int = 15) -> str:
        if self.error:
            return f"ERROR: {self.error}"
        lines = [" | ".join(self.columns)]
        lines += [" | ".join(str(value) for value in row) for row in self.rows[:max_rows]]
        if len(self.rows) > max_rows:
            lines.append(f"… ({len(self.rows)} rows total)")
        return "\n".join(lines) if self.rows else " | ".join(self.columns) + "\n(no rows)"


# `mode=ro` protects only the opened file: ATTACH could still read any SQLite file the user can read (other apps
# keep their data in SQLite) and create or write new ones. The authorizer lets model-written SQL read and nothing else.
_READING = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}
_SCHEMA_PRAGMAS = {"table_info", "table_xinfo", "table_list", "index_list", "index_info", "foreign_key_list"}
NOT_ALLOWED = "only reading queries on this database are allowed (SELECT); ATTACH, PRAGMA settings and writes are not"


def _authorize(action: int, arg1: str | None, _arg2: str | None, _db: str | None, _trigger: str | None) -> int:
    if action in _READING:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() in _SCHEMA_PRAGMAS:  # schema lookups only
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def run_query(db_path: Path, sql: str, *, timeout_s: float = 5.0, max_rows: int = 1000) -> QueryResult:
    """Execute one reading statement on a read-only connection; errors are returned, not raised."""
    deadline = time.monotonic() + timeout_s
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            # Returning non-zero from the progress handler aborts runaway queries (cartesian joins).
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            db.set_authorizer(_authorize)
            cursor = db.execute(sql)
            columns = [column[0] for column in cursor.description or []]
            return QueryResult(columns, cursor.fetchmany(max_rows))
    except sqlite3.DatabaseError as exc:
        if "not authorized" in str(exc):
            return QueryResult(error=f"{type(exc).__name__}: {NOT_ALLOWED}")
        return QueryResult(error=f"{type(exc).__name__}: {exc}")
    except sqlite3.Error as exc:
        return QueryResult(error=f"{type(exc).__name__}: {exc}")
    except sqlite3.Warning as exc:  # e.g. "You can only execute one statement at a time."
        return QueryResult(error=str(exc))
