"""The one I/O seam of the LLM layer: POST JSON, get JSON back.

Everything protocol-specific (request shape, response parsing, error meaning) is pure and lives in
`llm/protocols/`. A transport only moves bytes — httpx on the server, `pyodide.http.pyfetch` in
the browser, `fetch` in a future TypeScript engine — so every runtime shares the same mapping code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class TransportError(Exception):
    """Connection-level failure (DNS, refused, timeout): always worth a retry."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any  # parsed JSON body (or {"raw": text} when the body is not JSON)


class ChatTransport(Protocol):
    async def post_json(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
    ) -> HttpResponse:
        """POST `body` as JSON; raise TransportError on connection failure, never on HTTP status."""
        ...
