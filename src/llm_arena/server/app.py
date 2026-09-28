"""The local app: a FastAPI server over ArenaService, plus the static web UI.

Every endpoint mirrors a service method and speaks the JSON contracts in `contracts/schemas`, so the
web UI can switch between this server (HttpBackend) and the in-browser engine (WorkerBackend)
without changing any view. Binds to 127.0.0.1 and allows only localhost origins: the app can spend
money through configured keys, so it must not be reachable from other machines or sites.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from llm_arena.adapters.server.report_html import build_report
from llm_arena.api import RunListing, RunStartedResponse, RuntimeResponse, SetKey, StartRun
from llm_arena.core.errors import ArenaError
from llm_arena.llm.errors import LLMError
from llm_arena.report.leaderboard import Leaderboard
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.run import new_run_id
from llm_arena.scenarios.manifest import ScenarioManifest
from llm_arena.server.channels import Channels
from llm_arena.server.keys import KeyStore
from llm_arena.service import ArenaService, Estimate, RunBundle

DEFAULT_PORT = 8787
DEV_SERVER_PORT = 5173  # Vite dev server for the web UI


def local_origins(port: int) -> list[str]:
    return [f"http://{host}:{p}" for p in (port, DEV_SERVER_PORT) for host in ("127.0.0.1", "localhost")]


def create_app(
    service: ArenaService,
    *,
    runs_dir: Path,
    static_dir: Path | None = None,
    keys: KeyStore | None = None,
    port: int = DEFAULT_PORT,
) -> FastAPI:
    app = FastAPI(title="LLM Arena", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=local_origins(port), allow_methods=["*"], allow_headers=["*"])
    channels = Channels()
    keys = keys or KeyStore()

    @app.get("/api/runtime", response_model=RuntimeResponse)
    async def runtime() -> RuntimeResponse:
        info = await service.runtime_info()
        return RuntimeResponse(**info.model_dump(), keys=keys.status())

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

    @app.post("/api/estimate", response_model=Estimate)
    async def estimate(experiment: ExperimentConfig) -> Estimate:
        try:
            return await service.estimate(experiment)
        except (ArenaError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs", response_model=RunStartedResponse, status_code=202)
    async def start_run(body: StartRun) -> RunStartedResponse:
        run_id = body.run_id or new_run_id(body.experiment.name)
        if "/" in run_id or ".." in run_id:
            raise HTTPException(status_code=400, detail="invalid run id")
        channel = channels.get(run_id)
        try:
            await service.start_run(body.experiment, sink=channel.publish, run_id=run_id, live=body.live)
        except (ArenaError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RunStartedResponse(run_id=run_id)

    @app.get("/api/leaderboard", response_model=list[Leaderboard])
    def leaderboard(scenario: str | None = None) -> list[Leaderboard]:
        run_ids = [path.parent.name for path in runs_dir.glob("*/arena.duckdb")]
        return service.leaderboards(run_ids, scenario=scenario)

    @app.get("/api/runs", response_model=list[RunListing])
    def list_runs() -> list[RunListing]:
        listings = []
        for run_dir in sorted(runs_dir.glob("*/arena.duckdb"), reverse=True):
            run_id = run_dir.parent.name
            try:
                data = service.store_factory(run_id).load_run()
            except Exception:  # a run being written by another process: skip it this time
                continue
            listings.append(
                RunListing(
                    run_id=run_id,
                    name=str(data.run.get("name", "")),
                    created_at=str(data.run.get("created_at", "")),
                    trials=len(data.trials),
                    passed=sum(bool(t["passed"]) for t in data.trials),
                    errors=sum(t["status"] != "ok" for t in data.trials),
                    active=run_id in channels and not channels.get(run_id).finished,
                )
            )
        return listings

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str) -> StreamingResponse:
        if run_id not in channels:
            raise HTTPException(status_code=404, detail="no live run with this id (finished runs: use /bundle)")

        async def stream() -> AsyncIterator[str]:
            async for event in channels.get(run_id).subscribe():
                yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel(run_id: str) -> dict[str, str]:
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
    def report(run_id: str) -> FileResponse:
        _require_run(runs_dir, run_id)
        return FileResponse(build_report(runs_dir / run_id, inline_plotly=True), media_type="text/html")

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


def _require_run(runs_dir: Path, run_id: str) -> None:
    if "/" in run_id or ".." in run_id or not (runs_dir / run_id / "arena.duckdb").exists():
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")


_PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>LLM Arena</title>
<style>body{font:15px/1.5 system-ui,sans-serif;max-width:720px;margin:48px auto;padding:0 16px}
code{background:#f3f2ee;padding:1px 5px;border-radius:4px}</style></head><body>
<h1>LLM Arena</h1><p>The API is running. The web UI is not built yet: run <code>make web</code>, then restart
<code>arena ui</code>.</p><p>API: <a href="/docs">/docs</a> · <a href="/api/scenarios">/api/scenarios</a> ·
<a href="/api/models">/api/models</a> · <a href="/api/runs">/api/runs</a></p></body></html>"""
