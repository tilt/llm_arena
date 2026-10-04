"""The loopback server stays private even when a hostile page can reach localhost."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_arena.core.errors import ConfigError, RunConflictError, RunLimitError
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.runner.config import configured_dev_origin
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.server.app import MAX_REQUEST_BYTES, create_app
from llm_arena.server.session import COOKIE_NAME, load_ui_token, session_cookie, token_path
from llm_arena.service import ArenaService
from server_test_client import ORIGIN, SESSION_TOKEN


def _app(tmp_path: Path, *, token: str = SESSION_TOKEN, dev_origin: str | None = None) -> FastAPI:
    service = ArenaService(
        Runtime(client_factory=lambda spec: ScriptedLLM(["x"], spec=spec)),
        store_factory=lambda _: MemoryStore(),
    )
    return create_app(service, runs_dir=tmp_path, session_token=token, dev_origin=dev_origin)


LOCKED_ROUTES = [
    ("GET", "/api/runtime", None),
    ("GET", "/api/scenarios", None),
    ("GET", "/api/models", None),
    ("PUT", "/api/keys/openai", {"key": "x"}),
    ("DELETE", "/api/keys/openai", None),
    ("POST", "/api/estimate", {}),
    ("POST", "/api/runs", {}),
    ("GET", "/api/scenarios/reflection_sql/tasks", None),
    ("GET", "/api/presets", None),
    ("PUT", "/api/presets/test", {}),
    ("DELETE", "/api/presets/test", None),
    ("GET", "/api/leaderboard", None),
    ("GET", "/api/runs", None),
    ("GET", "/api/runs/missing/events", None),
    ("PATCH", "/api/runs/missing", {}),
    ("POST", "/api/runs/missing/cancel", None),
    ("GET", "/api/runs/missing/bundle", None),
    ("GET", "/api/runs/missing/trials/trial/trace", None),
    ("GET", "/api/runs/missing/artifacts/file", None),
    ("GET", "/api/runs/missing/report", None),
]


@pytest.mark.parametrize(("method", "path", "body"), LOCKED_ROUTES)
def test_every_api_route_requires_authentication(tmp_path: Path, method: str, path: str, body: object) -> None:
    client = TestClient(_app(tmp_path), base_url=ORIGIN)
    response = client.request(method, path, json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.json()["auth"] == "required"


def test_session_exchange_uses_derived_host_only_cookie_and_rotation_invalidates_it(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), base_url=ORIGIN)
    assert client.post("/api/session", json={"token": "wrong"}, headers={"Origin": ORIGIN}).status_code == 401

    response = client.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": ORIGIN})
    cookie = response.headers["set-cookie"]
    assert response.status_code == 204
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Max-Age=2592000" in cookie and "Domain=" not in cookie and "Secure" not in cookie
    assert SESSION_TOKEN not in cookie and session_cookie(SESSION_TOKEN) in cookie
    assert client.get("/api/runtime").status_code == 200

    rotated = TestClient(_app(tmp_path, token="rotated-token"), base_url=ORIGIN)
    rotated.cookies.set(COOKIE_NAME, session_cookie(SESSION_TOKEN))
    assert rotated.get("/api/runtime").status_code == 401


def test_static_shell_is_public_but_api_and_session_are_not(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>Arena</title>")
    (static / "version.json").write_text('{"build":"public"}')
    app = create_app(
        ArenaService(Runtime(client_factory=lambda spec: ScriptedLLM(["x"], spec=spec)), store_factory=lambda _: MemoryStore()),
        runs_dir=tmp_path,
        static_dir=static,
        session_token=SESSION_TOKEN,
    )  # fmt: skip
    client = TestClient(app, base_url=ORIGIN)
    assert client.get("/").status_code == 200
    assert client.get("/version.json").json() == {"build": "public"}
    assert client.get("/api/runtime").status_code == 401
    assert client.post("/api/session", json={"token": SESSION_TOKEN}).status_code == 403


def test_host_origin_and_fetch_metadata_are_enforced_before_routing(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), base_url=ORIGIN)
    for host in (
        "attacker.example",
        "127.0.0.1.attacker.example",
        "127.0.0.1@attacker.example",
        "localhost.",
        "127.0.0.1:99999",
        "::1",
    ):
        assert client.get("/api/runtime", headers={"Host": host}).status_code == 400
    assert client.get("/api/runtime", headers={"Host": "[::1]:8787"}).status_code == 401
    assert (
        client.post(
            "/api/session",
            json={"token": SESSION_TOKEN},
            headers={"Host": "attacker.example", "Origin": "http://attacker.example"},
        ).status_code
        == 400
    )
    assert client.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": ORIGIN}).status_code == 204
    assert client.post("/api/estimate", json={}, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/estimate", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    # Authenticated non-browser clients may omit both browser headers and reach normal validation.
    assert client.post("/api/estimate", json={}).status_code == 400


def test_only_explicit_development_origin_is_accepted(tmp_path: Path) -> None:
    dev = "http://127.0.0.1:5173"
    client = TestClient(_app(tmp_path, dev_origin=dev), base_url=ORIGIN)
    assert client.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": dev}).status_code == 204
    preflight = client.options(
        "/api/session",
        headers={"Origin": dev, "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == dev
    assert preflight.headers["access-control-allow-credentials"] == "true"
    denied = TestClient(_app(tmp_path), base_url=ORIGIN)
    assert denied.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": dev}).status_code == 403


def test_development_origin_configuration_is_exact_and_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_DEV_ORIGIN", "http://localhost:5173/")
    assert configured_dev_origin() == "http://localhost:5173"
    for value in ("https://attacker.example", "http://localhost", "http://localhost:5173/path", "*"):
        monkeypatch.setenv("ARENA_DEV_ORIGIN", value)
        with pytest.raises(ConfigError):
            configured_dev_origin()


def test_shell_and_api_get_distinct_security_headers(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), base_url=ORIGIN)
    shell = client.get("/")
    api = client.get("/api/runtime")
    for response in (shell, api):
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "script-src 'self'" in shell.headers["content-security-policy"]
    assert "worker-src 'none'" in shell.headers["content-security-policy"]
    assert api.headers["content-security-policy"].startswith("default-src 'none'")


@pytest.mark.parametrize(("error", "status"), [(RunConflictError("active"), 409), (RunLimitError("full"), 429)])
def test_run_admission_errors_have_distinct_status_and_no_event_channel(
    tmp_path: Path, error: Exception, status: int
) -> None:
    service = ArenaService(
        Runtime(client_factory=lambda spec: ScriptedLLM(["x"], spec=spec)),
        store_factory=lambda _: MemoryStore(),
    )

    async def refuse(*args: object, **kwargs: object) -> str:
        raise error

    service.start_run = refuse  # type: ignore[method-assign]
    client = TestClient(create_app(service, runs_dir=tmp_path, session_token=SESSION_TOKEN), base_url=ORIGIN)
    assert client.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": ORIGIN}).status_code == 204
    body = {
        "run_id": "refused",
        "experiment": {
            "name": "test",
            "scenarios": ["reflection_sql"],
            "configs": [{"name": "one", "roles": {"*": "openai:gpt-4.1-nano"}}],
        },
    }
    assert client.post("/api/runs", json=body).status_code == status
    assert client.get("/api/runs/refused/events").status_code == 404


def test_token_is_persistent_private_and_rotated_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    first = load_ui_token()
    path = token_path()
    assert path.read_text().strip() == first
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_ui_token() == first
    second = load_ui_token(rotate=True)
    assert second != first and path.read_text().strip() == second
    assert not list(path.parent.glob(".ui-token.*"))


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform has no no-follow file open")
def test_token_loader_does_not_follow_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("stolen")
    token = tmp_path / "config" / "ui-token"
    token.parent.mkdir()
    token.symlink_to(target)
    with pytest.raises(OSError):
        load_ui_token(path=token)
    assert target.read_text() == "stolen"


def test_security_csp_contains_no_wildcards_or_unsafe_script_sources(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), base_url=ORIGIN)
    csp = client.get("/").headers["content-security-policy"]
    assert "*" not in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert not re.search(r"https?://", csp)


def test_request_body_limit_applies_before_json_parsing(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), base_url=ORIGIN)
    assert client.post("/api/session", json={"token": SESSION_TOKEN}, headers={"Origin": ORIGIN}).status_code == 204
    response = client.post(
        "/api/estimate",
        content=b"{" + b"x" * MAX_REQUEST_BYTES + b"}",
        headers={"Content-Type": "application/json", "Origin": ORIGIN},
    )
    assert response.status_code == 413
    assert str(MAX_REQUEST_BYTES) in response.text
