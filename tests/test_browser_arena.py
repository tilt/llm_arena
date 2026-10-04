"""The browser engine entry (BrowserArena), exercised on the server with fake fetch/sandbox bridges."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from llm_arena.adapters.browser.arena import BrowserArena
from llm_arena.adapters.browser.js_sandbox import JsSandbox
from llm_arena.adapters.server.subprocess_sandbox import SubprocessSandbox
from llm_arena.core.errors import ConfigError
from llm_arena.llm.transport import HttpResponse

GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def _chat(content: str) -> HttpResponse:
    body = {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "model": "gpt-4.1-nano"}  # fmt: skip
    return HttpResponse(200, body)


class FakeFetch:
    """Stands in for pyodide's fetch: chat completions, model lists and dataset downloads."""

    def __init__(self) -> None:
        self.chat_bodies: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    async def post_json(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
    ) -> HttpResponse:
        self.chat_bodies.append(body)
        self.headers.append(headers)
        return _chat('{"verdict": "accept", "issues": []}' if "verdict" in json.dumps(body) else GOOD_SQL)

    async def get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        assert "api.openai.com/v1/models" in url
        return HttpResponse(200, {"data": [{"id": "gpt-4.1-nano"}, {"id": "whisper-1"}]})

    async def get_bytes(self, url: str) -> bytes:
        assert url.startswith("https://huggingface.co/datasets/google/IFEval/resolve/")
        row = {
            "key": 1,
            "prompt": "Answer without commas.",
            "instruction_id_list": ["punctuation:no_comma"],
            "kwargs": [{}],
        }
        return (json.dumps(row) + "\n").encode()


def _arena(sandbox: Any = None) -> tuple[BrowserArena, FakeFetch, list[dict[str, Any]]]:
    fetch, events = FakeFetch(), []
    arena = BrowserArena(
        transport=fetch, http_get=fetch.get, get_bytes=fetch.get_bytes, emit=lambda raw: events.append(json.loads(raw)),
        sandbox=sandbox,
    )  # fmt: skip
    return arena, fetch, events


EXPERIMENT = {"name": "b", "scenarios": ["reflection_sql"], "task_ids": ["harborview_march_rentals"],
              "configs": [{"name": "nano", "roles": {"*": "openai:gpt-4.1-nano"}}]}  # fmt: skip


async def test_models_need_keys_and_use_the_catalog_builders() -> None:
    arena, _, _ = _arena()
    models = json.loads(await arena.models())
    assert models["models"] == [] and models["unavailable"]["openai"] == "no API key set"
    arena.set_key("openai", "sk-test")
    models = json.loads(await arena.models(refresh=True))
    assert [m["ref"] for m in models["models"]] == ["openai:gpt-4.1-nano"]
    runtime = json.loads(await arena.runtime())
    assert runtime["runtime"] == "browser" and runtime["keys"] == {"openai": "session", "anthropic": "missing"}
    assert "sk-test" not in json.dumps(runtime)


async def test_full_run_over_fetch_with_events_and_bundle() -> None:
    arena, fetch, events = _arena()
    arena.set_key("openai", "sk-test")
    await arena.models(refresh=True)
    run_id = await arena.start_run(json.dumps({"experiment": EXPERIMENT, "run_id": "r1"}))
    await arena.service.wait(run_id)
    assert [e["event"]["type"] for e in events][-1] == "run_finished" and {e["run_id"] for e in events} == {"r1"}
    bundle = json.loads(arena.bundle("r1"))
    assert bundle["trials"][0]["passed"] is True
    assert json.loads(arena.runs())[0] == {**json.loads(arena.runs())[0], "run_id": "r1", "active": False, "passed": 1}
    assert fetch.headers[0]["Authorization"] == "Bearer sk-test"


async def test_local_models_and_missing_keys_are_rejected_before_running() -> None:
    arena, fetch, events = _arena()
    local = {**EXPERIMENT, "configs": [{"name": "l", "roles": {"*": "ollama:qwen3:4b"}}]}
    with pytest.raises(ConfigError, match="remote models only"):
        await arena.start_run(json.dumps({"experiment": local}))
    with pytest.raises(ConfigError, match="set your openai API key"):
        await arena.start_run(json.dumps({"experiment": EXPERIMENT}))
    assert not fetch.chat_bodies and not events  # nothing ran
    with pytest.raises(ConfigError, match="browser mode supports"):
        arena.set_key("ollama", "x")


async def test_benchmark_datasets_are_prefetched_before_planning() -> None:
    arena, _, _ = _arena()
    arena.set_key("openai", "sk-test")
    experiment = {
        "name": "i",
        "scenarios": ["ifeval"],
        "limit": 1,
        "configs": [{"name": "n", "roles": {"model": "openai:gpt-4.1-nano"}}],
    }
    estimate = json.loads(await arena.estimate(json.dumps(experiment)))
    assert estimate["trials"] == 1


async def test_js_sandbox_bridge_round_trips_files() -> None:
    server = SubprocessSandbox()

    async def run_js(code: str, files_json: str, collect_json: str, timeout_s: float) -> str:
        files = {name: base64.b64decode(value) for name, value in json.loads(files_json).items()}
        result = await server.run(code, files=files, collect=tuple(json.loads(collect_json)), timeout_s=timeout_s)
        return json.dumps({"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode,
                           "timed_out": result.timed_out, "files": {k: base64.b64encode(v).decode() for k, v in result.files.items()}})  # fmt: skip

    sandbox = JsSandbox(run_js)
    assert sandbox.network_isolation == "not network-isolated"
    result = await sandbox.run("print(open('in.txt').read()); open('out.bin','wb').write(b'\\x00\\x01')", files={"in.txt": "hi"},
                               collect=("out.bin",))  # fmt: skip
    assert result.ok and result.stdout.strip() == "hi" and result.files["out.bin"] == b"\x00\x01"


async def test_selftest_reproduces_the_conformance_vectors() -> None:
    arena, _, _ = _arena(sandbox=SubprocessSandbox())
    vectors = {path.stem: json.loads(path.read_text()) for path in (CONTRACTS / "conformance").glob("*.json")}
    results = json.loads(await arena.selftest(json.dumps(vectors)))
    assert results and all(r["status"] == "pass" for r in results), results
