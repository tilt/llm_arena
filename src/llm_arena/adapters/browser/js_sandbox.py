"""Sandbox port backed by a JavaScript function: the web page runs model code in a separate, killable
Pyodide worker (see web/src/engine/sandbox.worker.ts) and returns the result as JSON."""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable

from llm_arena.sandbox.base import ExecResult

# (code, files as JSON {name: base64}, collect globs as JSON, timeout in seconds) -> result JSON
JsRunner = Callable[[str, str, str, float], Awaitable[str]]


class JsSandbox:
    def __init__(self, run_js: JsRunner) -> None:
        self._run_js = run_js

    async def run(
        self,
        code: str,
        *,
        files: dict[str, bytes | str] | None = None,
        collect: tuple[str, ...] = (),
        timeout_s: float = 30.0,
    ) -> ExecResult:
        encoded = {
            name: base64.b64encode(content.encode("utf-8") if isinstance(content, str) else content).decode("ascii")
            for name, content in (files or {}).items()
        }
        raw = await self._run_js(code, json.dumps(encoded), json.dumps(list(collect)), timeout_s)
        data = json.loads(str(raw))
        return ExecResult(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            returncode=int(data.get("returncode", 1)),
            timed_out=bool(data.get("timed_out", False)),
            files={name: base64.b64decode(value) for name, value in (data.get("files") or {}).items()},
            duration_s=float(data.get("duration_s", 0.0)),
        )
