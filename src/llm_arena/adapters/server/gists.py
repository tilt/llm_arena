"""GitHub Gist I/O for shareable claims, on behalf of the local app.

The local UI runs under `connect-src 'self'`, so it reaches GitHub only through these calls. Every input is checked
before a URL is built (hex gist ids and revisions, page 1-3, numeric comment ids), requests go only to the fixed
GitHub API base, redirects are never followed, responses are capped at 2 MB and calls time out after 10 s. The token
comes from the caller (the app's key store); this module never reads the environment.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

API = "https://api.github.com/gists"
CLAIM_FILE = "claim.json"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_COMMENT_CHARS = 65_536
MAX_PAGES = 3
PER_PAGE = 100
TIMEOUT_S = 10.0
_GIST_ID = re.compile(r"^[0-9a-f]{20,32}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_COMMENT_ID = re.compile(r"^[0-9]{1,20}$")

FailureKind = Literal["invalid", "unreachable", "server", "throttled", "rate_limited", "not_found", "unauthorized"]


@dataclass
class GistFailure(Exception):
    """Why a GitHub call failed, in the states the claim page tells apart (unreachable, 5xx, throttled with a wait,
    the 60-per-hour limit without a token, 404, a missing or rejected token)."""

    kind: FailureKind
    message: str
    retry_after_s: int | None = None

    def __str__(self) -> str:
        return self.message

    @property
    def status(self) -> int:
        return {"invalid": 400, "not_found": 404, "unauthorized": 401, "throttled": 429, "rate_limited": 429}.get(
            self.kind, 502
        )

    def detail(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "retry_after_s": self.retry_after_s}


def check_gist_id(value: str) -> str:
    if not _GIST_ID.fullmatch(value):
        raise GistFailure("invalid", "a gist id is 20-32 hex characters")
    return value


def check_revision(value: str) -> str:
    if not _REVISION.fullmatch(value):
        raise GistFailure("invalid", "a gist revision is 40 hex characters")
    return value


def check_comment_id(value: str) -> str:
    if not _COMMENT_ID.fullmatch(value):
        raise GistFailure("invalid", "a comment id is a number")
    return value


class GistClient:
    def __init__(
        self,
        token: Callable[[], str | None],
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._token = token
        self._transport = transport
        self._timeout_s = timeout_s

    # ---- reads ---------------------------------------------------------------------------------------------------
    async def claim(self, gist_id: str, revision: str) -> dict[str, Any]:
        """The claim file at a pinned revision, plus what the page shows around it (owner, head revision, comment
        count). A link always pins a revision, so a later edit can't change what was shared."""
        gist_id, revision = check_gist_id(gist_id), check_revision(revision)
        pinned = await self._get(f"{API}/{gist_id}/{revision}")
        head = await self._get(f"{API}/{gist_id}")
        file = (pinned.get("files") or {}).get(CLAIM_FILE)
        if not isinstance(file, dict) or not isinstance(file.get("content"), str):
            raise GistFailure("not_found", f"this gist has no {CLAIM_FILE}")
        if file.get("truncated"):
            raise GistFailure("invalid", f"{CLAIM_FILE} is too large to be a claim")
        history = head.get("history") or []
        return {
            "claim": file["content"],
            "owner": str((pinned.get("owner") or {}).get("login") or ""),
            "head_revision": str(history[0].get("version") or "") if history else revision,
            "comments": int(head.get("comments") or 0),
            "html_url": str(head.get("html_url") or ""),
        }

    async def comments(self, gist_id: str, page: int) -> list[dict[str, Any]]:
        gist_id = check_gist_id(gist_id)
        if not 1 <= page <= MAX_PAGES:
            raise GistFailure("invalid", f"comment pages are 1-{MAX_PAGES}")
        rows = await self._get(f"{API}/{gist_id}/comments", params={"per_page": PER_PAGE, "page": page})
        if not isinstance(rows, list):
            raise GistFailure("server", "GitHub returned an unexpected comment list")
        return [_comment(row) for row in rows if isinstance(row, dict)]

    async def comment(self, gist_id: str, comment_id: str) -> dict[str, Any] | None:
        """One comment, or None when GitHub says it is gone (the posted check tells "removed" from "can't check")."""
        gist_id, comment_id = check_gist_id(gist_id), check_comment_id(comment_id)
        try:
            row = await self._get(f"{API}/{gist_id}/comments/{comment_id}")
        except GistFailure as failure:
            if failure.kind == "not_found":
                return None
            raise
        return _comment(row)

    # ---- writes (need a token) -----------------------------------------------------------------------------------
    async def create(self, claim: str, description: str) -> dict[str, Any]:
        body = {"description": description[:200], "public": True, "files": {CLAIM_FILE: {"content": claim}}}
        created = await self._send("POST", API, body)
        history = created.get("history") or []
        return {
            "gist_id": check_gist_id(str(created.get("id") or "")),
            "revision": check_revision(str(history[0].get("version") or "")) if history else "",
            "html_url": str(created.get("html_url") or ""),
            "owner": str((created.get("owner") or {}).get("login") or ""),
        }

    async def post_comment(self, gist_id: str, body: str) -> dict[str, Any]:
        gist_id = check_gist_id(gist_id)
        if len(body) > MAX_COMMENT_CHARS:
            raise GistFailure("invalid", f"a comment holds at most {MAX_COMMENT_CHARS} characters")
        return _comment(await self._send("POST", f"{API}/{gist_id}/comments", {"body": body}))

    # ---- transport -----------------------------------------------------------------------------------------------
    def _headers(self, *, required: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif required:
            raise GistFailure("unauthorized", "posting needs a GitHub token with the Gists permission")
        return headers

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", url, params=params, headers=self._headers())

    async def _send(self, method: str, url: str, body: dict[str, Any]) -> Any:
        return await self._request(method, url, json_body=body, headers=self._headers(required=True))

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport, follow_redirects=False) as http,
                http.stream(method, url, params=params, json=json_body, headers=headers) as response,
            ):
                data = await _read_capped(response)
        except httpx.TimeoutException as exc:
            raise GistFailure("unreachable", "GitHub didn't answer within 10 seconds") from exc
        except httpx.TransportError as exc:
            raise GistFailure("unreachable", "GitHub can't be reached from this machine") from exc
        _raise_for(response, data)
        try:
            return json.loads(data)
        except ValueError as exc:
            raise GistFailure("server", "GitHub returned something that isn't JSON") from exc


async def _read_capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise GistFailure("invalid", "GitHub's response is larger than 2 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _raise_for(response: httpx.Response, data: bytes) -> None:
    status = response.status_code
    if status < 300:
        return
    if 300 <= status < 400:
        raise GistFailure("server", "GitHub answered with a redirect, which is not followed")
    if status == 404:
        raise GistFailure("not_found", "This gist or comment doesn't exist (deleted, or the link is wrong)")
    if status == 401:
        raise GistFailure("unauthorized", "GitHub rejected the token")
    retry = response.headers.get("retry-after")
    if status in (403, 429) and (retry or response.headers.get("x-ratelimit-remaining") == "0"):
        reset = response.headers.get("x-ratelimit-reset")
        if retry and retry.isdigit():
            raise GistFailure("throttled", f"GitHub asks to wait {retry} s", int(retry))
        authenticated = "authorization" in {key.lower() for key in response.request.headers}
        kind: FailureKind = "throttled" if authenticated else "rate_limited"
        message = "GitHub's rate limit is used up" + (
            "" if authenticated else " (60 requests per hour without a token)"
        )
        wait = None
        if reset and reset.isdigit():
            wait = max(0, int(reset) - int(time.time()))
        raise GistFailure(kind, message, wait)
    if status == 403:
        raise GistFailure("unauthorized", "GitHub refused this (does the token have the Gists permission?)")
    if status >= 500:
        raise GistFailure("server", f"GitHub had an error ({status}); try again shortly")
    raise GistFailure("invalid", f"GitHub refused the request ({status})")


def _comment(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise GistFailure("server", "GitHub returned an unexpected comment")
    body = str(row.get("body") or "")
    return {
        "id": int(row.get("id") or 0),
        "user": {"login": str((row.get("user") or {}).get("login") or "")[:100]},
        "created_at": str(row.get("created_at") or "")[:40],
        "updated_at": str(row.get("updated_at") or "")[:40],
        "body": body[:MAX_COMMENT_CHARS],
        "html_url": str(row.get("html_url") or "")[:300],
    }
