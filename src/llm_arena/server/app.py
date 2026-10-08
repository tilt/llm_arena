"""The local app: a FastAPI server over ArenaService, plus the static web UI.

Every endpoint mirrors a service method and speaks the JSON contracts in `contracts/schemas`, so the
web UI can switch between this server (HttpBackend) and the in-browser engine (WorkerBackend)
without changing any view. Binds to 127.0.0.1 and allows only localhost origins: the app can spend
money through configured keys, so it must not be reachable from other machines or sites.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from llm_arena.adapters.server.report_html import render_report, report_csp
from llm_arena.api import (
    EndpointView,
    RunListing,
    RunStartedResponse,
    RuntimeResponse,
    SaveEndpoint,
    SetKey,
    StartRun,
    run_listing,
)
from llm_arena.core.errors import ArenaError, RunConflictError, RunLimitError
from llm_arena.llm.errors import LLMError
from llm_arena.llm.registry import EndpointStore
from llm_arena.llm.spec import Endpoint, key_transport_ok
from llm_arena.report.leaderboard import Leaderboard
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import progress
from llm_arena.runner.presets import ModelPreset
from llm_arena.runner.rename import RenameRun
from llm_arena.runner.run import new_run_id, valid_run_id
from llm_arena.scenarios.brief import TaskView
from llm_arena.scenarios.manifest import ScenarioManifest
from llm_arena.server.channels import Channels, RunChannel
from llm_arena.server.keys import KeyStore
from llm_arena.server.session import COOKIE_NAME, cookie_matches, session_cookie, token_matches
from llm_arena.service import ArenaService, Estimate, RunBundle

DEFAULT_PORT = 8787
MAX_REQUEST_BYTES = 1024 * 1024


class RequestSizeLimitMiddleware:
    """Buffer at most one request MiB so chunked bodies cannot bypass Content-Length checks."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length", b"")
        if raw_length.isdigit() and int(raw_length) > self.max_bytes:
            await self._reject(scope, receive, send)
            return
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break
        iterator = iter(messages)

        async def replay() -> Message:
            return next(iterator, {"type": "http.request", "body": b"", "more_body": False})

        await self.app(scope, replay, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = Response(
            content=f"Request body exceeds {self.max_bytes} bytes; reduce the experiment or uploaded data.",
            status_code=413,
            media_type="text/plain",
        )
        await response(scope, receive, send)


def local_origins(port: int, dev_origin: str | None = None) -> list[str]:
    origins = [f"http://{host}:{port}" for host in ("127.0.0.1", "localhost", "[::1]")]
    return [*origins, *([dev_origin] if dev_origin else [])]


class SessionRequest(BaseModel):
    token: str


class LocalSecurityMiddleware:
    """Reject rebinding/cross-site requests, authenticate APIs, and attach local-app headers."""

    _HOSTS = {"127.0.0.1", "localhost", "::1"}
    _MUTATIONS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp, token: str, port: int, dev_origin: str | None = None) -> None:
        self.app = app
        self.token = token
        self.origins = frozenset(local_origins(port, dev_origin))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        host = request.headers.get("host", "")
        if not self._trusted_host(host):
            await self._reject(
                scope,
                receive,
                send,
                400,
                f"This server only answers on 127.0.0.1/localhost (Host header was {request.headers.get('host', '')})",
            )
            return
        path = scope.get("path", "")
        authenticated = cookie_matches(self.token, request.cookies.get(COOKIE_NAME))
        if request.method in self._MUTATIONS and not self._mutation_allowed(request, authenticated):
            await self._reject(
                scope, receive, send, 403, "Cross-site mutation refused; reopen the link printed by arena ui."
            )
            return
        if path.startswith("/api/") and path != "/api/session" and not authenticated:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Open the link printed by arena ui, or run arena ui --link", "auth": "required"},
            )
            await self._send_response(response, scope, receive, send)
            return

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                self._security_headers(headers, path)
            await send(message)

        await self.app(scope, receive, secure_send)

    def _trusted_host(self, authority: str) -> bool:
        try:
            parsed = urlsplit(f"//{authority}")
            port = parsed.port
        except ValueError:
            return False
        return (
            parsed.hostname in self._HOSTS
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and (port is None or 0 < port <= 65535)
        )

    def _mutation_allowed(self, request: Request, authenticated: bool) -> bool:
        origin = request.headers.get("origin")
        if origin:
            return origin in self.origins
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site:
            return fetch_site in ("same-origin", "none")
        return authenticated

    async def _reject(self, scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        await self._send_response(JSONResponse(status_code=status, content={"detail": detail}), scope, receive, send)

    async def _send_response(self, response: Response, scope: Scope, receive: Receive, send: Send) -> None:
        self._security_headers(response.headers, str(scope.get("path", "")))
        await response(scope, receive, send)

    @staticmethod
    def _security_headers(headers: MutableHeaders, path: str) -> None:
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if "Content-Security-Policy" in headers:
            return
        if path.startswith("/api/"):
            headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        else:
            headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
                "connect-src 'self'; worker-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )


def create_app(
    service: ArenaService,
    *,
    runs_dir: Path,
    static_dir: Path | None = None,
    keys: KeyStore | None = None,
    endpoints: EndpointStore | None = None,
    port: int = DEFAULT_PORT,
    session_token: str | None = None,
    dev_origin: str | None = None,
) -> FastAPI:
    session_token = session_token or secrets.token_urlsafe(32)
    app = FastAPI(title="LLM Arena", version="0.1.0")
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=local_origins(port, dev_origin),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LocalSecurityMiddleware, token=session_token, port=port, dev_origin=dev_origin)

    @app.exception_handler(RequestValidationError)
    async def readable_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"msg": "invalid request", "loc": ()}
        field = ".".join(str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path"))
        context = first.get("ctx")
        cause = context.get("error") if isinstance(context, dict) else None
        message = str(cause or first.get("msg", "invalid request"))
        return JSONResponse(status_code=400, content={"detail": f"{field}: {message}" if field else message})

    channels = Channels()
    # The UI is served from disk, the API from the code loaded at startup: after `make web` a reloaded page can be
    # newer than this process. Reporting the build seen at startup lets the page notice and ask for a restart.
    ui_build = _ui_build(static_dir)
    listing_cache: dict[str, tuple[float, RunListing]] = {}
    keys = keys or KeyStore()
    endpoints = endpoints if endpoints is not None else EndpointStore()

    def endpoint_view(endpoint: Endpoint) -> EndpointView:
        return EndpointView(**endpoint.model_dump(), key=keys.endpoint_source(endpoint))

    @app.post("/api/session", status_code=204)
    def create_session(body: SessionRequest, response: Response) -> Response:
        if not token_matches(session_token, body.token):
            raise HTTPException(status_code=401, detail="The UI token is invalid; run arena ui --link for a new link")
        response.set_cookie(
            COOKIE_NAME,
            session_cookie(session_token),
            httponly=True,
            samesite="strict",
            max_age=30 * 24 * 60 * 60,
            path="/",
        )
        response.status_code = 204
        return response

    @app.get("/api/runtime", response_model=RuntimeResponse)
    async def runtime() -> RuntimeResponse:
        info = await service.runtime_info()
        return RuntimeResponse(**info.model_dump(), keys=keys.status(), ui_build=ui_build)

    @app.get("/api/scenarios", response_model=list[ScenarioManifest])
    def scenarios() -> list[ScenarioManifest]:
        return service.list_scenarios()

    @app.get("/api/models")
    async def models(refresh: bool = False, snapshots: bool = False) -> dict[str, Any]:
        catalog = await service.catalog(refresh=refresh)
        return {
            "models": [entry.as_dict() for entry in catalog.filter(snapshots=snapshots)],
            "aliases": {name: spec.model_dump() for name, spec in service.model_specs.items()},
            "unavailable": catalog.errors,
        }

    @app.put("/api/keys/{provider}", status_code=204)
    async def set_key(provider: str, body: SetKey) -> None:
        try:
            keys.set(provider, body.key)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await service.catalog(refresh=True)  # a new key can unlock a provider's model list

    @app.delete("/api/keys/{provider}", status_code=204)
    async def clear_key(provider: str) -> None:
        try:
            keys.clear(provider)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await service.catalog(refresh=True)

    @app.get("/api/endpoints", response_model=list[EndpointView])
    def list_endpoints() -> list[EndpointView]:
        return [endpoint_view(endpoint) for endpoint in endpoints.all().values()]

    @app.put("/api/endpoints/{endpoint_id}", response_model=EndpointView)
    async def save_endpoint(endpoint_id: str, body: SaveEndpoint) -> EndpointView:
        previous = endpoints.get(endpoint_id)
        moved = previous is not None and previous.base_url != body.base_url.strip().rstrip("/")
        try:
            endpoint = Endpoint(
                id=endpoint_id,
                # A YAML-configured key env stays bound to its URL: moving the endpoint unbinds it.
                api_key_env=previous.api_key_env if previous and not moved else None,
                **body.model_dump(exclude={"key", "salt"}),
                **_salt(body.salt or (previous.salt if previous else None)),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=_first_error(exc)) from exc
        if body.key and not key_transport_ok(endpoint.base_url):
            raise HTTPException(
                status_code=400,
                detail="a key is only sent over https:// (or to a local or private "
                "network address); change the URL to https",
            )
        if previous and moved:
            keys.clear_endpoint_key(endpoint_id)  # a session key is bound to the host it was entered for
        endpoints.put(endpoint)
        if body.key:
            try:
                keys.set_endpoint_key(endpoint_id, body.key)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        await service.catalog(refresh=True)
        return endpoint_view(endpoint)

    @app.delete("/api/endpoints/{endpoint_id}", status_code=204)
    async def remove_endpoint(endpoint_id: str) -> None:
        removed = endpoints.remove(endpoint_id)
        if removed is None:
            raise HTTPException(status_code=404, detail=f"unknown endpoint {endpoint_id!r}")
        keys.clear_endpoint_key(endpoint_id)
        await service.catalog(refresh=True)

    @app.post("/api/estimate", response_model=Estimate)
    async def estimate(experiment: ExperimentConfig) -> Estimate:
        try:
            return await service.estimate(experiment)
        except (ArenaError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs", response_model=RunStartedResponse, status_code=202)
    async def start_run(body: StartRun) -> RunStartedResponse:
        run_id = body.run_id or new_run_id(body.experiment.name)
        if not valid_run_id(run_id):
            raise HTTPException(status_code=400, detail="invalid run id")
        channel = RunChannel()
        try:
            await service.start_run(body.experiment, sink=channel.publish, run_id=run_id, live=body.live)
        except RunConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RunLimitError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except (ArenaError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        channels.add(run_id, channel)
        return RunStartedResponse(run_id=run_id)

    @app.get("/api/scenarios/{scenario_id}/tasks", response_model=list[TaskView])
    def tasks(scenario_id: str) -> list[TaskView]:
        try:
            return service.tasks(scenario_id)
        except ArenaError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/presets", response_model=dict[str, ModelPreset])
    def presets() -> dict[str, ModelPreset]:
        return service.presets

    @app.put("/api/presets/{name}", response_model=dict[str, ModelPreset])
    def save_preset(name: str, profile: ModelPreset) -> dict[str, ModelPreset]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
            raise HTTPException(status_code=400, detail="profile names use lowercase letters, digits, - and _")
        return service.save_preset(name, profile)

    @app.delete("/api/presets/{name}", response_model=dict[str, ModelPreset])
    def reset_preset(name: str) -> dict[str, ModelPreset]:
        return service.save_preset(name, None)

    @app.get("/api/leaderboard", response_model=list[Leaderboard])
    def leaderboard(scenario: str | None = None) -> list[Leaderboard]:
        run_ids = _existing_run_ids(runs_dir)
        return service.leaderboards(run_ids, scenario=scenario)

    @app.get("/api/runs", response_model=list[RunListing])
    def list_runs() -> list[RunListing]:
        """Newest first, live runs with their progress. Finished runs are cached by database mtime, so the UI
        can poll this cheaply while something runs."""
        listings = []
        for run_id in _existing_run_ids(runs_dir):
            db_file = runs_dir / run_id / "arena.duckdb"
            live = run_id in channels and not channels.get(run_id).finished
            stamp = db_file.stat().st_mtime
            cached = listing_cache.get(run_id)
            if cached is None or cached[0] != stamp or live:
                try:
                    data = service.store_factory(run_id).load_run()
                except Exception:  # a run being written by another process: skip it this time
                    continue
                cached = (stamp, run_listing(run_id, data.run, data.trials))
                listing_cache[run_id] = cached
            listing = cached[1]
            if run_id in channels:
                history = channels.get(run_id).history
                listing = listing.model_copy(update={"active": live, "progress": progress(history) if live else None})
            listings.append(listing)
        return sorted(listings, key=lambda r: (r.active, r.created_at, r.run_id), reverse=True)

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str) -> StreamingResponse:
        if not valid_run_id(run_id) or run_id not in channels:
            raise HTTPException(status_code=404, detail="no live run with this id (finished runs: use /bundle)")

        async def stream() -> AsyncIterator[str]:
            async for event in channels.get(run_id).subscribe():
                yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.patch("/api/runs/{run_id}", status_code=204)
    def rename_run(run_id: str, body: RenameRun) -> Response:
        """New display name and setup names for a finished run; ids and links stay."""
        _require_run(runs_dir, run_id, mutation=True)
        try:
            service.rename_run(run_id, body)
        except ArenaError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        listing_cache.pop(run_id, None)
        return Response(status_code=204)

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel(run_id: str) -> dict[str, str]:
        if not valid_run_id(run_id) or run_id not in channels or channels.get(run_id).finished:
            raise HTTPException(status_code=404, detail=f"unknown active run {run_id!r}")
        service.cancel(run_id)
        return {"run_id": run_id, "status": "cancelling"}

    @app.get("/api/runs/{run_id}/bundle", response_model=RunBundle)
    def bundle(run_id: str, traces: bool = True, artifacts: bool = False) -> RunBundle:
        """`traces=false` for the in-app report (traces load per trial); `artifacts=true` for a full export."""
        _require_run(runs_dir, run_id)
        return service.run_bundle(run_id, traces=traces, artifacts=artifacts)

    @app.get("/api/runs/{run_id}/trials/{trial_id}/trace")
    def trial_trace(run_id: str, trial_id: str) -> dict[str, Any]:
        _require_run(runs_dir, run_id)
        trace = service.trial_trace(run_id, trial_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=f"no trace for trial {trial_id}")
        return trace

    @app.get("/api/runs/{run_id}/artifacts/{key:path}")
    def artifact(run_id: str, key: str) -> Response:
        _require_run(runs_dir, run_id)
        found = service.artifact(run_id, key)
        if found is None:
            raise HTTPException(status_code=404, detail="no such artifact")
        data, media_type = found
        # Artifacts are model-generated: never let the browser sniff them into something executable.
        headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"}
        return Response(content=data, media_type=media_type, headers=headers)

    @app.get("/api/runs/{run_id}/report")
    def report(run_id: str) -> HTMLResponse:
        _require_run(runs_dir, run_id)
        nonce = secrets.token_urlsafe(24)
        return HTMLResponse(
            render_report(runs_dir / run_id, inline_plotly=True, nonce=nonce),
            headers={"Content-Security-Policy": report_csp(nonce, True)},
        )

    @app.middleware("http")
    async def cache_policy(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Only content-hashed assets may be cached; the HTML shell must be revalidated, or browsers
        # keep running an old UI (with old asset hashes) after an upgrade.
        response = await call_next(request)
        if not request.url.path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    if static_dir is not None and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def placeholder() -> str:
            return _PLACEHOLDER

    return app


def _salt(salt: str | None) -> dict[str, str]:
    """Keep an endpoint's salt across edits: its identity then changes only with its URL."""
    return {"salt": salt} if salt else {}


def _first_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "invalid value")).removeprefix("Value error, ")
    return f"{field}: {message}" if field else message


def _ui_build(static_dir: Path | None) -> str:
    try:
        return str(json.loads((static_dir / "version.json").read_text(encoding="utf-8"))["build"]) if static_dir else ""
    except (OSError, ValueError, KeyError):
        return ""


def _require_run(runs_dir: Path, run_id: str, *, mutation: bool = False) -> None:
    if mutation and not valid_run_id(run_id):
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if not run_id or any(char in run_id for char in ("/", "\\", "\0")) or any(ord(char) < 32 for char in run_id):
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    root = runs_dir.resolve()
    candidate = runs_dir / run_id
    if candidate.is_symlink():
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    try:
        resolved = candidate.resolve()
    except OSError:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}") from None
    if resolved.parent != root or not (resolved / "arena.duckdb").is_file():
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")


def _existing_run_ids(runs_dir: Path) -> list[str]:
    found: list[str] = []
    for child in runs_dir.iterdir() if runs_dir.exists() else ():
        try:
            _require_run(runs_dir, child.name)
        except HTTPException:
            continue
        found.append(child.name)
    return found


_PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>LLM Arena</title>
<style>body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:48px auto;padding:0 16px}
code{background:#f3f2ee;padding:1px 5px;border-radius:4px}</style></head><body>
<h1>LLM Arena</h1><p>The API is running. The web UI is not built yet: run <code>make web</code>, then restart
<code>arena ui</code>.</p><p>API: <a href="/docs">/docs</a> · <a href="/api/scenarios">/api/scenarios</a> ·
<a href="/api/models">/api/models</a> · <a href="/api/runs">/api/runs</a></p></body></html>"""
