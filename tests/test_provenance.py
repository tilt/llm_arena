"""Guard against accidental copy-paste from the (copyrighted) course material.

The course repo is a sibling checkout (`../course_agentic_ai`); when it is absent this test is
skipped. We compare long token shingles: a 20-token overlap is far beyond what shared idioms
(`client.chat.completions.create(model=..., messages=...)`) produce, so any hit means copied text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COURSE = REPO.parent / "course_agentic_ai" / "assignments"
SHINGLE = 20
_TOKEN = re.compile(r"\w+")


def _shingles(text: str) -> set[tuple[str, ...]]:
    tokens = _TOKEN.findall(text.lower())
    return {tuple(tokens[i : i + SHINGLE]) for i in range(len(tokens) - SHINGLE + 1)}


@pytest.mark.skipif(not COURSE.exists(), reason="course material not checked out next to this repo")
def test_no_long_verbatim_overlap_with_course_material() -> None:
    course: set[tuple[str, ...]] = set()
    for path in COURSE.rglob("*"):
        if path.suffix in {".py", ".md"} and ".ipynb_checkpoints" not in path.parts:
            course |= _shingles(path.read_text(encoding="utf-8", errors="ignore"))
    offenders = {}
    for folder in ("src", "configs", "docs", "tests"):
        for path in (REPO / folder).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".j2"} and path.name != Path(__file__).name:
                overlap = _shingles(path.read_text(encoding="utf-8")) & course
                if overlap:
                    offenders[str(path.relative_to(REPO))] = " ".join(next(iter(overlap)))
    assert not offenders, f"verbatim overlap with course material: {offenders}"
