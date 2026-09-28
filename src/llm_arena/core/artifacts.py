"""Files produced or consumed by a step (images sent to a vision model, rendered charts, generated files).

A trace attaches them to the span that used them; the run's store persists the bytes (run folder
on the server, the run bundle in the browser). Caps keep a runaway trial from filling the disk.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel, Field

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TRIAL_BYTES = 20 * 1024 * 1024


class ArtifactRef(BaseModel):
    name: str
    media_type: str
    size: int
    key: str = Field(default="", description="store key (<trial>/<seq>-<name>); empty when not stored")
    note: str = Field(default="", description="why it was not stored, if it was not")


ArtifactSink = Callable[[str, bytes, str], ArtifactRef]  # (name, data, media_type) -> stored reference


def safe_name(name: str) -> str:
    cleaned = re.sub(r"\.{2,}", ".", re.sub(r"[^A-Za-z0-9._-]+", "_", name)).strip("._") or "artifact"
    return cleaned[:80]


def artifact_key(trial_id: str, seq: int, name: str) -> str:
    return f"{safe_name(trial_id)}/{seq:03d}-{safe_name(name)}"


def valid_key(key: str) -> bool:
    """Keys come back from URLs: allow only <trial>/<file> made of safe characters (no traversal)."""
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", key)) and ".." not in key
