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


def run_query(db_path: Path, sql: str, *, timeout_s: float = 5.0, max_rows: int = 1000) -> QueryResult:
    """Execute one statement on a read-only connection; errors are returned, not raised."""
    deadline = time.monotonic() + timeout_s
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            # Returning non-zero from the progress handler aborts runaway queries (cartesian joins).
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            cursor = db.execute(sql)
            columns = [column[0] for column in cursor.description or []]
            return QueryResult(columns, cursor.fetchmany(max_rows))
    except sqlite3.Error as exc:
        return QueryResult(error=f"{type(exc).__name__}: {exc}")
    except sqlite3.Warning as exc:  # e.g. "You can only execute one statement at a time."
        return QueryResult(error=str(exc))
