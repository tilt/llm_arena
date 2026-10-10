"""The local app's claim routes: GitHub only through the bounded gist adapter, drafts from stored runs, and the key
store's GitHub entry. GitHub is an httpx.MockTransport; nothing leaves the machine."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.adapters.server.gists import GistClient
from llm_arena.claims import Swap, repro_comment
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.ports import Runtime
from llm_arena.runner.run import ExperimentRunner
from llm_arena.server.app import create_app
from llm_arena.server.keys import KeyStore
from llm_arena.service import ArenaService
from server_test_client import ORIGIN, SESSION_TOKEN, authenticated_client
from test_claims import MINI, SPECS, TASKS, factory

GIST = "a" * 32
REV = "b" * 40


class GitHub:
    """A scripted GitHub: records every request; `respond` decides the answer."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._respond(request)

        return httpx.MockTransport(handler)


def app(tmp_path: Path, github: GitHub, *, token: str | None = None) -> TestClient:
    keys = KeyStore()
    service = ArenaService(Runtime(client_factory=factory), store_factory=lambda run_id: DuckDBStore(tmp_path / run_id),
                           model_specs=SPECS)  # fmt: skip
    gists = GistClient(token=lambda: token, transport=github.transport())
    return authenticated_client(create_app(service, runs_dir=tmp_path, keys=keys, session_token=SESSION_TOKEN,
                                           gists=gists))  # fmt: skip


def ok(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


async def stored_run(tmp_path: Path, experiment: ExperimentConfig, run_id: str) -> None:
    store = DuckDBStore(tmp_path / run_id)
    await ExperimentRunner(experiment, Runtime(client_factory=factory), store=store, model_specs=SPECS,
                           run_id=run_id).run()  # fmt: skip


def mine() -> ExperimentConfig:
    return ExperimentConfig.model_validate({"name": "mine", "scenarios": ["reflection_sql"], "task_ids": TASKS,
                                            "configs": [{"name": "mine", "roles": {"*": MINI}}]})  # fmt: skip


def test_ids_pages_and_comment_ids_are_checked_before_any_request(tmp_path: Path) -> None:
    github = GitHub(lambda request: ok({}))
    client = app(tmp_path, github)
    assert client.get(f"/api/claims/gists/xyz/{REV}").status_code == 400
    assert client.get(f"/api/claims/gists/{GIST}/nothex").status_code == 400
    assert client.get(f"/api/claims/gists/{GIST}/comments", params={"page": 4}).status_code == 400
    assert client.get(f"/api/claims/gists/{GIST}/comments/12a").status_code == 400
    assert client.get(f"/api/claims/gists/{'A' * 32}/{REV}").status_code == 400  # uppercase is not a gist id
    assert github.requests == []


def test_reads_go_only_to_the_github_api_and_map_each_failure(tmp_path: Path) -> None:
    claim_file = {"files": {"claim.json": {"content": "{}"}}, "owner": {"login": "alice"}}
    head = {"history": [{"version": "c" * 40}], "comments": 3, "html_url": "https://gist.github.com/x"}
    github = GitHub(lambda request: ok(claim_file if request.url.path.endswith(REV) else head))
    found = app(tmp_path, github).get(f"/api/claims/gists/{GIST}/{REV}").json()
    assert found == {"claim": "{}", "owner": "alice", "head_revision": "c" * 40, "comments": 3,
                     "html_url": "https://gist.github.com/x"}  # fmt: skip
    assert {str(r.url).split("?")[0] for r in github.requests} == {
        f"https://api.github.com/gists/{GIST}/{REV}", f"https://api.github.com/gists/{GIST}"}  # fmt: skip

    def status_of(respond: Callable[[httpx.Request], httpx.Response]) -> tuple[int, dict[str, Any]]:
        response = app(tmp_path, GitHub(respond)).get(f"/api/claims/gists/{GIST}/comments")
        return response.status_code, response.json()["detail"]

    assert status_of(lambda r: ok({}, 404))[1]["kind"] == "not_found"
    assert status_of(lambda r: ok({}, 503))[1]["kind"] == "server"
    assert status_of(lambda r: ok({}, 301, {"location": "https://evil.example"}))[1]["kind"] == "server"
    limited = status_of(lambda r: ok({}, 403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}))
    assert limited[0] == 429 and limited[1]["kind"] == "rate_limited" and "60" in limited[1]["message"]
    throttled = status_of(lambda r: ok({}, 429, {"retry-after": "30"}))
    assert throttled[1] == {"kind": "throttled", "message": "GitHub asks to wait 30 s", "retry_after_s": 30}

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    assert status_of(unreachable)[1]["kind"] == "unreachable"
    huge = status_of(lambda r: httpx.Response(200, content=b"[" + b'"x",' * 700_000 + b'"x"]'))
    assert "2 MB" in huge[1]["message"]


def test_a_gone_comment_is_404_and_the_others_cannot_check(tmp_path: Path) -> None:
    assert app(tmp_path, GitHub(lambda r: ok({}, 404))).get(f"/api/claims/gists/{GIST}/comments/42").status_code == 404
    assert app(tmp_path, GitHub(lambda r: ok({}, 502))).get(f"/api/claims/gists/{GIST}/comments/42").status_code == 502


def test_claim_routes_need_the_session(tmp_path: Path) -> None:
    keys = KeyStore()
    service = ArenaService(Runtime(client_factory=factory), store_factory=lambda run_id: DuckDBStore(tmp_path / run_id))
    client = TestClient(create_app(service, runs_dir=tmp_path, keys=keys, session_token=SESSION_TOKEN), base_url=ORIGIN)
    for path in (f"/api/claims/gists/{GIST}/{REV}", f"/api/claims/gists/{GIST}/comments"):
        assert client.get(path, headers={"Origin": ORIGIN}).status_code in (401, 403)
    assert client.post("/api/claims/thread", json={}, headers={"Origin": ORIGIN}).status_code in (401, 403)


async def test_share_beat_and_post_through_the_server(tmp_path: Path) -> None:
    await stored_run(tmp_path, mine(), "mine")
    posted: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/gists":
            body = json.loads(request.content)
            assert body["public"] is True and list(body["files"]) == ["claim.json"]
            assert body["description"].startswith("llm_arena claim · reflection_sql v")
            return ok({"id": GIST, "history": [{"version": REV}], "html_url": "https://gist/x", "owner": {"login": "me"}},
                      201)  # fmt: skip
        posted.append(json.loads(request.content))
        return ok({"id": 7, "user": {"login": "me"}, "created_at": "t", "updated_at": "t", "body": posted[-1]["body"]},
                  201)  # fmt: skip

    github = GitHub(respond)
    client = app(tmp_path, github, token="ghp_test")
    draft = client.post("/api/runs/mine/claim-draft", json={"names": {}}).json()
    assert draft["claim_json"] and draft["reasons"] == []
    created = client.post("/api/claims/gists", json={"claim": draft["claim_json"]}).json()
    assert created == {"gist_id": GIST, "revision": REV, "html_url": "https://gist/x", "owner": "me"}
    assert github.requests[-1].headers["authorization"] == "Bearer ghp_test"

    swap = Swap(role="critic", candidate="openai:gpt-4.1-nano").model_dump()
    config = client.post("/api/claims/experiment", json={"claim": draft["claim_json"], "swap": swap, "cap_usd": 1,
                                                         "gist_id": GIST, "revision": REV}).json()  # fmt: skip
    assert config["claim_ref"]["gist_id"] == GIST and config["budget_mode"] == "strict"
    await stored_run(tmp_path, ExperimentConfig.model_validate(config), "beat")
    repro = client.post("/api/runs/beat/repro-draft", json={"claim": draft["claim_json"], "seen": [1]}).json()
    assert repro["block"] and repro["reasons"] == []
    assert client.post(f"/api/claims/gists/{GIST}/comments", json={"body": "hello"}).status_code == 400
    assert client.post(f"/api/claims/gists/{GIST}/comments", json={"body": repro["block"]}).status_code == 200
    assert posted == [{"body": repro["block"]}]
    refused = client.post(
        "/api/claims/experiment",
        json={
            "claim": draft["claim_json"],
            "swap": {"role": "critic", "candidate": "openai:gpt-4.1-mini#max_tokens=1024"},
        },
    )
    assert refused.status_code == 400 and "same model" in refused.json()["detail"]  # fmt: skip
    stats = client.post(
        "/api/claims/thread",
        json={
            "claim": draft["claim_json"],
            "author": "me",
            "comments": [
                {"id": 7, "user": {"login": "bob"}, "created_at": "t", "updated_at": "t", "body": repro["block"]}
            ],
        },
    ).json()
    assert stats["people"] == 1 and stats["rows"][0]["status"] == "counted"  # fmt: skip


def test_posting_without_a_token_is_refused_before_any_request(tmp_path: Path) -> None:
    github = GitHub(lambda request: ok({}))
    from llm_arena.claims import Repro

    block = repro_comment(Repro.model_validate({
        "arena_repro": 1, "claim_hash": "a" * 64, "scenario_version": "1", "task_fps_hash": "a" * 12,
        "baseline": {"setup_fp": "a" * 12, "passed": 0, "trials": 1, "errors": 0, "timeouts": 0, "budget_stopped": 0,
                     "cost_usd_per_task": 0},
        "per_task": [{"b": 0}], "engine": "local", "arena_version": "0",
    }))  # fmt: skip
    response = app(tmp_path, github).post(f"/api/claims/gists/{GIST}/comments", json={"body": block})
    assert response.status_code == 401 and github.requests == []


def test_the_github_token_is_a_key_store_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    keys = KeyStore()
    assert keys.status()["github"] == "missing" and keys.secret("github") is None
    keys.set("github", " ghp_x ")
    assert keys.status()["github"] == "session" and keys.secret("github") == "ghp_x"
    keys.clear("github")
    assert "GITHUB_TOKEN" not in os.environ
    assert {"openai", "anthropic", "typesafe", "tavily"} <= set(keys.status())  # model keys unchanged
