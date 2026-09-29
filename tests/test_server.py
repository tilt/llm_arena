from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.llm.catalog import Catalog, CatalogEntry
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.runner.ports import Runtime
from llm_arena.server.app import create_app
from llm_arena.server.keys import KeyStore
from llm_arena.service import ArenaService

SECRET = "sk-test-DO-NOT-LEAK-1234567890"
GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
NANO = ModelSpec(name="openai:gpt-4.1-nano", provider="openai", model="gpt-4.1-nano")
EXPERIMENT = {
    "name": "ui",
    "scenarios": ["reflection_sql"],
    "task_ids": ["harborview_march_rentals"],
    "configs": [{"name": "nano", "roles": {"*": "openai:gpt-4.1-nano"}}],
}


def _reply(messages: list[dict[str, object]]) -> str:
    return '{"verdict": "accept", "issues": []}' if "verdict" in str(messages) else GOOD_SQL


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def discover() -> Catalog:
        return Catalog(entries=[CatalogEntry(spec=NANO, source="openai")], errors={"lmstudio": "ConnectError"})

    def client_factory(spec: ModelSpec) -> LLMClient:
        return ScriptedLLM([_reply])

    service = ArenaService(
        Runtime(client_factory=client_factory, discover=discover, name="test"),
        store_factory=lambda run_id: DuckDBStore(tmp_path / run_id),
    )
    return TestClient(create_app(service, runs_dir=tmp_path, keys=KeyStore()))


def test_catalog_scenarios_and_estimate(client: TestClient) -> None:
    assert len(client.get("/api/scenarios").json()) == 16
    models = client.get("/api/models").json()
    assert [m["ref"] for m in models["models"]] == ["openai:gpt-4.1-nano"] and models["unavailable"] == {
        "lmstudio": "ConnectError"
    }
    estimate = client.post("/api/estimate", json=EXPERIMENT).json()
    assert estimate["trials"] == 1 and estimate["cost_usd"] > 0
    bad = client.post("/api/estimate", json={**EXPERIMENT, "configs": [{"name": "x", "roles": {"*": "ghost"}}]})
    assert bad.status_code == 400 and "ghost" in bad.json()["detail"]


def test_run_streams_events_then_serves_bundle_report_and_listing(client: TestClient) -> None:
    with client:  # keeps the app's event loop alive across requests, so the background run can finish
        started = client.post("/api/runs", json={"experiment": EXPERIMENT, "run_id": "r1"})
        assert started.status_code == 202 and started.json() == {"run_id": "r1"}
        with client.stream("GET", "/api/runs/r1/events") as stream:
            events = [json.loads(line[6:]) for line in stream.iter_lines() if line.startswith("data: ")]
        assert [e["type"] for e in events][-1] == "run_finished"
        assert any(e["type"] == "trial_finished" and e["passed"] for e in events)
        # A late subscriber replays the whole history.
        with client.stream("GET", "/api/runs/r1/events") as stream:
            assert sum(1 for line in stream.iter_lines() if line.startswith("data: ")) == len(events)
        bundle = client.get("/api/runs/r1/bundle").json()
        assert bundle["trials"][0]["passed"] and bundle["summary"]["configs"][0]["pass_rate"] == 1.0
        report = client.get("/api/runs/r1/report")
        assert report.status_code == 200 and "LLM Arena Report" in report.text
        listing = client.get("/api/runs").json()
        assert listing[0]["run_id"] == "r1" and listing[0]["passed"] == 1 and not listing[0]["active"]


def test_unknown_runs_and_traversal_are_rejected(client: TestClient) -> None:
    assert client.get("/api/runs/nope/bundle").status_code == 404
    assert client.get("/api/runs/..%2F..%2Fetc/bundle").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404
    assert client.post("/api/runs", json={"experiment": EXPERIMENT, "run_id": "../evil"}).status_code == 400


def test_session_keys_are_never_returned(client: TestClient) -> None:
    assert client.get("/api/runtime").json()["keys"]["openai"] == "missing"
    assert client.put("/api/keys/openai", json={"key": SECRET}).status_code == 204
    runtime = client.get("/api/runtime").json()
    assert runtime["keys"]["openai"] == "session"
    for path in ("/api/runtime", "/api/models", "/api/scenarios", "/api/runs", "/openapi.json"):
        assert SECRET not in client.get(path).text, path
    assert client.delete("/api/keys/openai").status_code == 204
    assert client.get("/api/runtime").json()["keys"]["openai"] == "missing"
    assert client.put("/api/keys/nope", json={"key": "x"}).status_code == 400


def test_placeholder_page_until_the_web_ui_is_built(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "make web" in page.text
    assert page.headers["cache-control"] == "no-cache"


def test_allowed_origins_follow_the_configured_port() -> None:
    from llm_arena.server.app import local_origins

    assert local_origins(9001) == [
        "http://127.0.0.1:9001", "http://localhost:9001", "http://127.0.0.1:5173", "http://localhost:5173",
    ]  # fmt: skip


def test_leaderboard_endpoint_lists_boards(client: TestClient) -> None:
    assert client.get("/api/leaderboard").json() == []


def test_scenario_tasks_endpoint(client: TestClient) -> None:
    tasks = client.get("/api/scenarios/reflection_sql/tasks").json()
    assert tasks and tasks[0]["expected"][0]["format"] == "table"
    assert client.get("/api/scenarios/nope/tasks").status_code == 404


def test_runs_are_listed_newest_first_with_their_scenarios(client: TestClient, tmp_path: Path) -> None:
    from llm_arena.adapters.server.duckdb_store import DuckDBStore

    for run_id, created in (("b-old", "2026-01-01 10:00:00"), ("a-new", "2026-02-01 10:00:00")):
        store = DuckDBStore(tmp_path / run_id)
        store.start_run(run_id, run_id, '{"scenarios": ["reflection_sql"]}')
        with store._db() as db:
            db.execute("UPDATE runs SET created_at = ?", [created])
    listed = client.get("/api/runs").json()
    assert [r["run_id"] for r in listed] == ["a-new", "b-old"]
    assert listed[0]["scenarios"] == ["reflection_sql"] and listed[0]["progress"] is None


def test_runtime_reports_the_ui_build_seen_at_startup(tmp_path: Path) -> None:
    # The page compares it with its own build: a newer page than server means the server needs a restart.
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>")
    (static / "version.json").write_text('{"build": "b1"}')
    service = ArenaService(Runtime(client_factory=lambda spec: ScriptedLLM(["x"])),
                           store_factory=lambda run_id: DuckDBStore(tmp_path / run_id))  # fmt: skip
    client = TestClient(create_app(service, runs_dir=tmp_path, static_dir=static, keys=KeyStore()))
    (static / "version.json").write_text('{"build": "b2"}')  # `make web` while the server runs
    assert client.get("/api/runtime").json()["ui_build"] == "b1"
    assert client.get("/version.json").json()["build"] == "b2"
