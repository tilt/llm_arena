"""Artifacts: files a step used or produced are kept with its span, within caps, in either store."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.adapters.server.subprocess_sandbox import SubprocessSandbox
from llm_arena.core import artifacts
from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient
from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import Runtime
from llm_arena.runner.run import ExperimentRunner
from llm_arena.server.app import create_app
from llm_arena.server.keys import KeyStore
from llm_arena.service import ArenaService

CHART = (
    "```python\nimport pandas as pd, matplotlib.pyplot as plt\ndf = pd.read_csv('energy.csv')\nfig, ax = plt.subplots()\n"
    "for site, g in df.groupby('site'):\n    ax.plot(g['month'], g['kwh'], label=site)\n"
    "ax.set_title('Monthly output'); ax.set_xlabel('Month'); ax.set_ylabel('kWh'); ax.legend()\n"
    "plt.savefig('chart.png', dpi=100)\n```"
)
SPECS = {
    "vlm": ModelSpec(name="vlm", provider="openai_compatible", model="vlm", capabilities=Capabilities(vision=True))
}


def test_attach_without_store_or_over_the_caps_keeps_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = Trace()
    with trace.span("step", "a") as span:
        ref = trace.attach(span, "x.png", b"123", "image/png")
    assert ref.key == "" and "no artifact store" in ref.note
    store = MemoryStore()
    trace.store_artifacts_with(lambda n, d, m: store.save_artifact("t1", n, d, m))
    monkeypatch.setattr("llm_arena.core.trace.MAX_FILE_BYTES", 4)
    with trace.span("step", "b") as span:
        small, big = (
            trace.attach(span, "a.txt", b"1234", "text/plain"),
            trace.attach(span, "b.txt", b"12345", "text/plain"),
        )
    assert small.key == "t1/000-a.txt" and big.key == "" and "size limit" in big.note
    assert store.load_artifact(small.key) == (b"1234", "text/plain")


def test_file_store_rejects_keys_outside_the_run(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "run")
    ref = store.save_artifact("trial/../x", "chart.png", b"png", "image/png")
    assert ".." not in ref.key and artifacts.valid_key(ref.key)
    assert store.load_artifact(ref.key) == (b"png", "image/png")
    for bad in ("../arena.duckdb", "a/../../x", "/etc/passwd", "a/b/c"):
        assert store.load_artifact(bad) is None
    store.clear_artifacts("trial/../x")
    assert store.load_artifact(ref.key) is None


def _factory(spec: ModelSpec) -> LLMClient:
    return ScriptedLLM(
        [lambda messages: '{"verdict": "accept"}' if "review charts" in str(messages[0]) else CHART], spec=spec
    )


async def test_chart_run_keeps_the_rendered_chart_and_the_image_the_critic_saw(tmp_path: Path) -> None:
    experiment = ExperimentConfig.model_validate({
        "name": "art", "scenarios": ["chart_codegen"], "task_ids": ["energy_lines"], "configs": [{"name": "c", "roles": {"*": "vlm"}}],
    })  # fmt: skip
    runtime = Runtime(client_factory=_factory, sandbox=SubprocessSandbox())
    store = DuckDBStore(tmp_path / "r")
    await ExperimentRunner(experiment, runtime, store=store, model_specs=SPECS, run_id="r").run()
    (trial,) = store.load_run().trials
    spans = store.load_trace(trial["trial_id"])["spans"]  # type: ignore[index]
    render = next(s for s in spans if s["name"] == "render_chart")
    assert render["step"] == "render" and [a["name"] for a in render["artifacts"]] == ["chart.png", "figure_spec.json"]
    critic_call = next(s for s in spans if s["kind"] == "llm_call" and s["role"] == "critic")
    assert critic_call["step"] == "critique" and critic_call["artifacts"][0]["media_type"] == "image/png"
    assert "artifact:" in str(critic_call["input"]) and "base64" not in str(critic_call["input"])
    result = next(s for s in spans if s["step"] == "end")
    assert result["artifacts"][0]["name"] == "chart.png"
    png, media = store.load_artifact(render["artifacts"][0]["key"])  # type: ignore[misc]
    assert media == "image/png" and png.startswith(b"\x89PNG")

    service = ArenaService(runtime, store_factory=lambda run_id: DuckDBStore(tmp_path / run_id))
    bundle = service.run_bundle("r", artifacts=True)
    assert base64.b64decode(bundle.artifacts[render["artifacts"][0]["key"]].data) == png
    assert service.run_bundle("r", traces=False).traces == {}

    client = TestClient(create_app(service, runs_dir=tmp_path, keys=KeyStore()))
    response = client.get(f"/api/runs/r/artifacts/{render['artifacts'][0]['key']}")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/runs/r/artifacts/..%2Farena.duckdb").status_code == 404
    assert client.get(f"/api/runs/r/trials/{trial['trial_id']}/trace").json()["spans"]


async def test_memory_store_artifacts_travel_in_the_bundle() -> None:
    store = MemoryStore()
    experiment = ExperimentConfig.model_validate({
        "name": "m", "scenarios": ["chart_codegen"], "task_ids": ["energy_lines"], "configs": [{"name": "c", "roles": {"*": "vlm"}}],
    })  # fmt: skip
    runtime = Runtime(client_factory=_factory, sandbox=SubprocessSandbox())
    await ExperimentRunner(experiment, runtime, store=store, model_specs=SPECS, run_id="m").run()
    bundle = ArenaService(runtime, store_factory=lambda _: store).run_bundle("m", artifacts=True)
    assert any(key.endswith("chart.png") for key in bundle.artifacts)
