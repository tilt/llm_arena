"""DuckDB RunStore: one database per run plus one JSON trace file per trial.

Layout:  runs/<run_id>/arena.duckdb   runs/<run_id>/traces/<trial_id>.json   runs/<run_id>/report.html

Connections are short-lived (one per operation): DuckDB locks the file per process, and a
long-held connection would stop a report or the local app from reading progress during a run.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from llm_arena.core.artifacts import ArtifactRef, artifact_key, safe_name, valid_key
from llm_arena.core.trace import Trace
from llm_arena.decisions.records import DECISION_COLUMNS, decision_rows
from llm_arena.eval.base import Score
from llm_arena.runner.memory_store import trace_payload, trial_row
from llm_arena.runner.ports import RunData, TrialRecord

_TRIAL_COLUMNS = (
    "trial_id", "run_id", "scenario", "pattern", "config", "task_id", "repeat", "status", "passed", "error", "final",
    "duration_s", "llm_calls", "tool_calls", "prompt_tokens", "completion_tokens", "cost_usd", "llm_latency_s",
    "judge_cost_usd", "roles_json", "params_json", "fingerprint", "scenario_version", "task_fp", "setup_json",
    "resume_key",
)  # fmt: skip

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, name TEXT, created_at TIMESTAMP DEFAULT current_timestamp, config_json TEXT
);
CREATE TABLE IF NOT EXISTS trials (
    trial_id TEXT PRIMARY KEY, run_id TEXT, scenario TEXT, pattern TEXT, config TEXT, task_id TEXT,
    repeat INTEGER, status TEXT, passed BOOLEAN, error TEXT, final TEXT, duration_s DOUBLE,
    llm_calls INTEGER, tool_calls INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER,
    cost_usd DOUBLE, llm_latency_s DOUBLE, judge_cost_usd DOUBLE, roles_json TEXT, params_json TEXT
);
-- Added later; runs created before get empty values (the leaderboard treats them as legacy).
ALTER TABLE trials ADD COLUMN IF NOT EXISTS fingerprint TEXT;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS scenario_version TEXT;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS task_fp TEXT;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS setup_json TEXT;
ALTER TABLE trials ADD COLUMN IF NOT EXISTS resume_key TEXT;
CREATE TABLE IF NOT EXISTS scores (
    trial_id TEXT, name TEXT, level TEXT, value DOUBLE, passed BOOLEAN, rationale TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    trial_id TEXT, scenario TEXT, config TEXT, task_id TEXT, repeat INTEGER, span INTEGER, point TEXT, question TEXT,
    qtype TEXT, policy TEXT, source TEXT, prediction TEXT, label TEXT, p_true DOUBLE, p_label DOUBLE,
    confidence DOUBLE, correct BOOLEAN, brier DOUBLE, escalated BOOLEAN, abstained BOOLEAN, human TEXT,
    latency_s DOUBLE, cost_usd DOUBLE
);
CREATE TABLE IF NOT EXISTS battles (
    scenario TEXT, task_id TEXT, config_a TEXT, config_b TEXT, winner TEXT, rationale TEXT
);
"""


class DuckDBStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        (run_dir / "traces").mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "arena.duckdb"
        with self._db() as db:
            db.execute(_SCHEMA)

    @contextmanager
    def _db(self, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(self.path), read_only=read_only)
        try:
            yield connection
        finally:
            connection.close()

    def start_run(self, run_id: str, name: str, config_json: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT OR IGNORE INTO runs (run_id, name, config_json) VALUES (?, ?, ?)", [run_id, name, config_json]
            )

    def completed_trials(self) -> dict[str, str]:
        with self._db() as db:
            rows = db.execute("SELECT trial_id, resume_key FROM trials WHERE status = 'ok'").fetchall()
        return {str(row[0]): str(row[1] or "") for row in rows}

    def save_trial(
        self, run_id: str, record: TrialRecord, scores: list[Score], trace: Trace, extra: dict[str, Any]
    ) -> None:
        row = trial_row(run_id, record)
        payload = trace_payload(record, scores, trace, extra)
        decisions = decision_rows(json.loads(json.dumps(payload["spans"], default=str)), row)
        with self._db() as db:
            # Resuming reruns failed trials: drop any earlier attempt first.
            db.execute("DELETE FROM scores WHERE trial_id = ?", [record.trial_id])
            db.execute("DELETE FROM decisions WHERE trial_id = ?", [record.trial_id])
            db.execute("DELETE FROM trials WHERE trial_id = ?", [record.trial_id])
            placeholders = ", ".join("?" for _ in _TRIAL_COLUMNS)
            db.execute(
                f"INSERT INTO trials ({', '.join(_TRIAL_COLUMNS)}) VALUES ({placeholders})",
                [row[column] for column in _TRIAL_COLUMNS],
            )
            if scores:
                db.executemany(
                    "INSERT INTO scores VALUES (?, ?, ?, ?, ?, ?)",
                    [[record.trial_id, s.name, s.level, s.value, s.passed, s.rationale] for s in scores],
                )
            if decisions:
                marks = ", ".join("?" for _ in DECISION_COLUMNS)
                db.executemany(
                    f"INSERT INTO decisions ({', '.join(DECISION_COLUMNS)}) VALUES ({marks})",
                    [[r[c] for c in DECISION_COLUMNS] for r in decisions],
                )
        (self.run_dir / "traces" / f"{record.trial_id}.json").write_text(
            json.dumps(payload, default=str, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def finals_for_battles(self, scenario: str) -> list[tuple[str, str, str]]:
        """(task_id, config, final) of repeat 0 of successful trials."""
        with self._db() as db:
            rows = db.execute(
                "SELECT task_id, config, final FROM trials WHERE scenario = ? AND repeat = 0 AND status = 'ok' "
                "ORDER BY task_id",
                [scenario],
            ).fetchall()
        return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]

    def save_battle(self, scenario: str, task_id: str, a: str, b: str, winner: str, rationale: str) -> None:
        with self._db() as db:
            db.execute("INSERT INTO battles VALUES (?, ?, ?, ?, ?, ?)", [scenario, task_id, a, b, winner, rationale])

    def has_battle(self, scenario: str, task_id: str, a: str, b: str) -> bool:
        with self._db() as db:
            row = db.execute(
                "SELECT count(*) FROM battles WHERE scenario = ? AND task_id = ? AND config_a = ? AND config_b = ?",
                [scenario, task_id, a, b],
            ).fetchone()
        return bool(row and row[0])

    def load_run(self) -> RunData:
        with self._db(read_only=True) as db:
            runs = _rows(db, "SELECT * FROM runs LIMIT 1")
            return RunData(
                run={**runs[0], "created_at": str(runs[0]["created_at"])[:19]} if runs else {},
                trials=_rows(db, "SELECT * FROM trials ORDER BY scenario, config, task_id, repeat"),
                scores=_rows(db, "SELECT * FROM scores"),
                battles=_rows(db, "SELECT * FROM battles"),
                decisions=_rows(db, "SELECT * FROM decisions ORDER BY trial_id, span, question"),
            )

    def clear_artifacts(self, trial_id: str) -> None:
        shutil.rmtree(self.run_dir / "artifacts" / safe_name(trial_id), ignore_errors=True)

    def save_artifact(self, trial_id: str, name: str, data: bytes, media_type: str) -> ArtifactRef:
        folder = self.run_dir / "artifacts" / safe_name(trial_id)
        folder.mkdir(parents=True, exist_ok=True)
        key = artifact_key(trial_id, len(list(folder.iterdir())), name)
        (self.run_dir / "artifacts" / key).write_bytes(data)
        return ArtifactRef(name=name, media_type=media_type, size=len(data), key=key)

    def load_artifact(self, key: str) -> tuple[bytes, str] | None:
        """Keys arrive from URLs: validated, and resolved strictly inside this run's artifact folder."""
        root = (self.run_dir / "artifacts").resolve()
        path = (root / key).resolve()
        if not valid_key(key) or root not in path.parents or not path.is_file():
            return None
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def load_trace(self, trial_id: str) -> dict[str, Any] | None:
        path = self.run_dir / "traces" / f"{trial_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _rows(db: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = db.execute(sql)
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
