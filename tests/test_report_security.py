"""The static report keeps names from configs and models as data, never as markup or script."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.adapters.server.report_html import build_report, script_json
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.ports import Runtime
from llm_arena.runner.run import ExperimentRunner

EVIL = "</script><script>alert(1)</script> "


def test_script_json_escapes_what_could_end_or_break_a_script() -> None:
    text = script_json({"name": EVIL, "amp": "a&b"})
    assert "<" not in text and ">" not in text and "&" not in text and " " not in text
    assert json.loads(text) == {"name": EVIL, "amp": "a&b"}


async def test_report_with_hostile_config_names_contains_no_injected_markup(tmp_path: Path) -> None:
    from test_runner_and_report import SPECS, factory

    experiment = ExperimentConfig.model_validate({
        "name": "xss", "scenarios": ["reflection_sql"], "task_ids": ["total_refunds"],
        "configs": [{"name": EVIL, "roles": {"*": "good"}}],
    })  # fmt: skip
    await ExperimentRunner(experiment, Runtime(client_factory=factory), store=DuckDBStore(tmp_path / "r"),
                           model_specs=SPECS, run_id="r").run()  # fmt: skip
    html = build_report(tmp_path / "r", inline_plotly=False).read_text(encoding="utf-8")
    assert "<script>alert(1)" not in html
    assert len(re.findall(r"<script\b", html)) == 2  # the Plotly loader and the report's own script, nothing else
    assert 'http-equiv="Content-Security-Policy"' in html and "default-src 'none'" in unescape(html)
    nonces = re.findall(r'<script nonce="([^"]+)"', html)
    assert len(nonces) == 2 and len(set(nonces)) == 1
    assert f"script-src 'nonce-{nonces[0]}'" in unescape(html)
    assert "'unsafe-inline'" not in unescape(html).split("style-src", 1)[0]
