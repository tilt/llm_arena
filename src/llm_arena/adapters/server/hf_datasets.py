"""Server dataset loader: pinned Hugging Face files (extra `benchmarks`), parquet read via DuckDB."""

from __future__ import annotations

import json
from typing import Any

import duckdb

from llm_arena.benchmarks.hf import HFSource
from llm_arena.scenarios.base import work_dir


class HubDatasetLoader:
    def load_rows(self, source: HFSource) -> list[dict[str, Any]]:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise RuntimeError("benchmarks need the extra: uv sync --extra benchmarks") from exc
        path = hf_hub_download(
            repo_id=source.repo,
            filename=source.filename,
            repo_type="dataset",
            revision=source.revision,
            cache_dir=str(work_dir() / "hf"),
        )
        if path.endswith(".jsonl"):
            with open(path, encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
        with duckdb.connect() as db:
            cursor = db.execute("SELECT * FROM read_parquet(?)", [path])
            columns = [column[0] for column in cursor.description or []]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
