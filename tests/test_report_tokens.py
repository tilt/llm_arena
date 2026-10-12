"""The exported HTML report repeats the app's color tokens; they must stay equal, since only the app's are contrast-
tested (web/src/lib/contrast.test.ts). The report's --seq list stands for the app's --seq-0 … --seq-6."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"--([a-z0-9-]+):\s*([^;]+);")


def _blocks(text: str) -> list[dict[str, str]]:
    """The light :root block, then the dark ones (media query, then data-theme), as token maps."""
    starts = [m.end() for m in re.finditer(r":root[^{]*\{", text)][:3]
    blocks = []
    for start in starts:
        body = text[start : text.index("}", start)]
        tokens = {name: value.strip().lower().replace(" ", "") for name, value in TOKEN.findall(body)}
        if "seq" in tokens:
            for i, color in enumerate(tokens.pop("seq").strip('"').split(",")):
                tokens[f"seq-{i}"] = color
        blocks.append(tokens)
    return blocks


def test_the_report_uses_the_apps_color_tokens() -> None:
    app = _blocks((ROOT / "web/src/app.css").read_text())
    report = _blocks((ROOT / "src/llm_arena/adapters/server/templates/report.html.j2").read_text())
    assert len(app) == len(report) == 3
    for theme, (ours, theirs) in enumerate(zip(report, app, strict=True)):
        shared = sorted(set(ours) & set(theirs))
        assert len(shared) >= 15, f"block {theme}: only {shared} shared"
        assert {k: ours[k] for k in shared} == {k: theirs[k] for k in shared}, f"block {theme} drifted from app.css"
