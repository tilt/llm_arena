"""Opt-in disk storage for the response cache (`ARENA_CACHE_DIR`)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_arena.llm.cache import cache_key
from llm_arena.llm.types import LLMResponse, ToolCall, Usage


class DiskCache:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def key(self, payload: dict[str, Any]) -> str:
        return cache_key(payload)

    def get(self, key: str) -> LLMResponse | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse(
            content=data["content"],
            tool_calls=[ToolCall(**call) for call in data["tool_calls"]],
            reasoning=data["reasoning"],
            # A cache hit costs nothing and takes no model time; report it that way.
            usage=Usage(data["usage"]["prompt_tokens"], data["usage"]["completion_tokens"], 0.0, 0.0),
            model=data["model"],
            raw_message=data["raw_message"],
            finish_reason=data["finish_reason"],
        )

    def put(self, key: str, response: LLMResponse) -> None:
        (self.directory / f"{key}.json").write_text(json.dumps(asdict(response), default=str), encoding="utf-8")
