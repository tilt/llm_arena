"""ChatTransport over httpx (server side)."""

from __future__ import annotations

from typing import Any

import httpx

from llm_arena.llm.transport import HttpResponse, TransportError


class HttpxTransport:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def post_json(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
    ) -> HttpResponse:
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(url, json=body, headers=headers, timeout=timeout_s)
        except httpx.TransportError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:2000]}
        return HttpResponse(response.status_code, data)
