"""The Docker sandbox, end to end. Skipped unless Docker runs and `make sandbox-image` was built."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from llm_arena.adapters.server.subprocess_sandbox import SANDBOX_IMAGE, DockerSandbox, docker_ready

pytestmark = pytest.mark.skipif(docker_ready() is not None, reason=f"Docker sandbox not available: {docker_ready()}")


def running() -> int:
    ps = ["docker", "ps", "-q", "--filter", f"ancestor={SANDBOX_IMAGE}"]
    return len(subprocess.run(ps, capture_output=True, text=True, check=False).stdout.split())


async def test_code_is_cut_off_from_network_host_and_privileges() -> None:
    sandbox = DockerSandbox()
    network = await sandbox.run("import urllib.request\nurllib.request.urlopen('http://192.0.2.1', timeout=1)")
    assert network.returncode != 0 and "URLError" in network.stderr
    probe = await sandbox.run(
        "import os\nstatus = open('/proc/self/status').read()\n"
        "print(os.path.exists('/Users'), status.split('CapEff:')[1].split()[0], status.split('NoNewPrivs:')[1].split()[0])"
    )
    assert probe.stdout.split() == ["False", "0000000000000000", "1"]
    memory = await sandbox.run("x = bytearray(3 * 1024**3)\nx[::4096] = b'1' * len(range(0, len(x), 4096))")
    assert memory.returncode == 137  # killed at the container's memory limit


async def test_timeouts_and_cancellation_leave_no_container_running() -> None:
    sandbox = DockerSandbox()
    assert (await sandbox.run("while True: pass", timeout_s=2)).timed_out
    task = asyncio.create_task(sandbox.run("while True: pass", timeout_s=60))
    await asyncio.sleep(2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(1)
    assert running() == 0


async def test_chart_scenario_renders_in_docker_and_keeps_the_png(tmp_path: Path) -> None:
    from llm_arena.adapters.server.duckdb_store import DuckDBStore
    from llm_arena.runner.config import ExperimentConfig
    from llm_arena.runner.ports import Runtime
    from llm_arena.runner.run import ExperimentRunner
    from test_artifacts import SPECS, _factory

    experiment = ExperimentConfig.model_validate({
        "name": "docker", "scenarios": ["chart_codegen"], "task_ids": ["energy_lines"], "configs": [{"name": "c", "roles": {"*": "vlm"}}],
    })  # fmt: skip
    store = DuckDBStore(tmp_path / "r")
    await ExperimentRunner(experiment, Runtime(client_factory=_factory, sandbox=DockerSandbox()), store=store,
                           model_specs=SPECS, run_id="r").run()  # fmt: skip
    (trial,) = store.load_run().trials
    assert trial["passed"], trial["error"]
    render = next(s for s in store.load_trace(trial["trial_id"])["spans"] if s["name"] == "render_chart")  # type: ignore[index]
    png = store.load_artifact(render["artifacts"][0]["key"])
    assert png is not None and png[0].startswith(b"\x89PNG")
