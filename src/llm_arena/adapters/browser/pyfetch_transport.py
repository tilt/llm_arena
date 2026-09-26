"""ChatTransport over the browser's fetch (Pyodide's `pyodide.http.pyfetch`).

Model providers must allow CORS: OpenAI echoes the page origin, Anthropic answers `*` when the
request carries `anthropic-dangerous-direct-browser-access: true` (ProtocolClient(browser=True)).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from llm_arena.llm.transport import HttpResponse, TransportError


class PyfetchTransport:
    async def post_json(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
    ) -> HttpResponse:
        from pyodide.http import pyfetch  # only importable inside Pyodide

        try:
            response = await asyncio.wait_for(
                pyfetch(url, method="POST", headers=headers, body=json.dumps(body)), timeout=timeout_s
            )
            text = await response.string()
        except Exception as exc:  # network errors surface as JS exceptions wrapped by Pyodide
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc
        try:
            data = json.loads(text)
        except ValueError:
            data = {"raw": text[:2000]}
        return HttpResponse(response.status, data)
