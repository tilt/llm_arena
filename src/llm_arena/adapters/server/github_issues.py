"""The board workflow's GitHub issue calls: read open claim submissions, answer them, close them.

Uses the workflow's own `GITHUB_TOKEN` (issues: write) against one fixed repository. Issue bodies are untrusted text:
they are parsed by `board.parse_submission`, never interpolated anywhere. Responses are size-capped like the gist
client's, with the same failure kinds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Literal

import httpx

from llm_arena.adapters.server.gists import TIMEOUT_S, GistFailure, _raise_for, _read_capped

API = "https://api.github.com/repos"
RETRY_MARK = "<!-- board-retry -->"
ACCEPTED, REJECTED, RETRY, INTERNAL = "board-accepted", "board-rejected", "board-retry", "board-internal-error"
ANSWER_LABELS = {ACCEPTED: "0e8a16", REJECTED: "b60205", RETRY: "fbca04", INTERNAL: "5319e7"}
_REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


class IssueClient:
    def __init__(
        self,
        token: Callable[[], str | None],
        repo: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
    ) -> None:
        if not _REPO.fullmatch(repo):
            raise ValueError(f"not a repository name: {repo!r}")
        self._token, self._repo, self._transport = token, f"{API}/{repo}", transport
        self._base = f"{self._repo}/issues"

    async def open_submissions(self, label: str) -> list[dict[str, Any]]:
        """The 100 oldest open submissions: a larger backlog drains over the next runs, in order."""
        rows = await self._request("GET", self._base, params={
            "state": "open", "labels": label, "sort": "created", "direction": "asc", "per_page": 100})  # fmt: skip
        return [_issue(row) for row in rows if isinstance(row, dict) and "pull_request" not in row]

    async def recent_count(self, label: str, login: str, since: str) -> int:
        """Submissions by `login` closed as accepted or rejected since `since` (the per-person daily limit). One page
        is enough: newest first, and anything past the limit only has to reach it."""
        rows = await self._request("GET", self._base, params={
            "state": "closed", "labels": label, "creator": login, "since": since, "per_page": 100})  # fmt: skip
        return sum(1 for row in rows if isinstance(row, dict) and str(row.get("created_at") or "") >= since
                   and {ACCEPTED, REJECTED} & set(_labels(row)) and INTERNAL not in _labels(row))  # fmt: skip

    async def attempts(self, number: int) -> int:
        """How many times a run already failed on this issue (the board's own retry comments)."""
        rows = await self._request("GET", f"{self._base}/{number}/comments", params={"per_page": 100})
        return sum(1 for row in rows if isinstance(row, dict) and RETRY_MARK in str(row.get("body") or ""))

    async def comment(self, number: int, body: str) -> None:
        await self._request("POST", f"{self._base}/{number}/comments", body={"body": body[:65_000]})

    async def ensure_labels(self, labels: dict[str, str]) -> None:
        """Create the answer labels that don't exist yet (name -> color), so adding them to an issue can't fail.
        Looked up by name, so it works however many labels the repository has."""
        for name, color in labels.items():
            try:
                await self._request("GET", f"{self._repo}/labels/{name}")
            except GistFailure as failure:
                if failure.kind != "not_found":
                    raise
                await self._request("POST", f"{self._repo}/labels", body={"name": name, "color": color})

    async def label(self, number: int, labels: list[str]) -> None:
        await self._request("POST", f"{self._base}/{number}/labels", body={"labels": labels})

    async def close(self, number: int, reason: Literal["completed", "not_planned"]) -> None:
        await self._request("PATCH", f"{self._base}/{number}", body={"state": "closed", "state_reason": reason})

    async def _request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None
    ) -> Any:
        token = self._token()
        if not token:
            raise GistFailure("unauthorized", "the board needs GITHUB_TOKEN to answer submissions")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "Authorization": f"Bearer {token}"}  # fmt: skip
        try:
            async with (
                httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport, follow_redirects=False) as http,
                http.stream(method, url, params=params, json=body, headers=headers) as response,
            ):
                data = await _read_capped(response)
        except httpx.TimeoutException as exc:
            raise GistFailure("unreachable", "GitHub didn't answer within 10 seconds") from exc
        except httpx.TransportError as exc:
            raise GistFailure("unreachable", "GitHub can't be reached") from exc
        _raise_for(response, data)
        return json.loads(data) if data else None


def _labels(row: dict[str, Any]) -> list[str]:
    return [str(label.get("name")) for label in row.get("labels") or [] if isinstance(label, dict)]


def _issue(row: dict[str, Any]) -> dict[str, Any]:
    user = row.get("user") or {}
    account = user.get("id") if isinstance(user, dict) else None
    return {
        "number": int(row.get("number") or 0),
        "body": str(row.get("body") or "")[:65_536],
        "user_login": str(user.get("login") or "")[:100] if isinstance(user, dict) else "",
        "user_id": account if isinstance(account, int) and not isinstance(account, bool) and account > 0 else None,
        "labels": _labels(row),
    }
