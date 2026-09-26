"""Pinned benchmark sources on the Hugging Face Hub, a loader port, and deterministic sampling.

Files are fetched at runtime (never vendored) and pinned to a commit so a subset means the same
items next month. Licences are listed in docs/licenses.md. Loading is runtime-specific:
`adapters.server.hf_datasets` on the server; the browser engine fetches `hub_url(source)`.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class HFSource:
    repo: str
    filename: str
    revision: str
    license: str


GSM8K = HFSource("openai/gsm8k", "main/test-00000-of-00001.parquet", "740312add88f781978c0658806c59bc2815b9866", "MIT")
MMLU_PRO = HFSource(
    "TIGER-Lab/MMLU-Pro", "data/test-00000-of-00001.parquet", "b189ec765aa7ed75c8acfea42df31fdae71f97be", "MIT"
)
HUMANEVAL = HFSource(
    "openai/openai_humaneval",
    "openai_humaneval/test-00000-of-00001.parquet",
    "7dce6050a7d6d172f3cc5c32aa97f52fa1a2e544",
    "MIT",
)
MBPP = HFSource(
    "google-research-datasets/mbpp",
    "sanitized/test-00000-of-00001.parquet",
    "4bb6404fdc6cacfda99d4ac4205087b89d32030c",
    "CC-BY-4.0",
)
IFEVAL = HFSource("google/IFEval", "ifeval_input_data.jsonl", "966cd89545d6b6acfd7638bc708b98261ca58e84", "Apache-2.0")


class DatasetLoader(Protocol):
    def load_rows(self, source: HFSource) -> list[dict[str, Any]]: ...


_loader: DatasetLoader | None = None


def configure_loader(loader: DatasetLoader) -> None:
    """Set by the runtime: the server uses the Hub client + DuckDB, the browser fetches `hub_url(source)`."""
    global _loader
    _loader = loader


def load_rows(source: HFSource) -> list[dict[str, Any]]:
    if _loader is None:
        raise RuntimeError("no dataset loader configured for this runtime (benchmarks.hf.configure_loader)")
    return _loader.load_rows(source)


def hub_url(source: HFSource) -> str:
    """Direct download URL at the pinned revision (served with CORS, so browsers can fetch it too)."""
    return f"https://huggingface.co/datasets/{source.repo}/resolve/{source.revision}/{source.filename}"


def stratified_sample(
    rows: list[dict[str, Any]], size: int, *, key: Callable[[dict[str, Any]], str] | None = None, seed: int = 0
) -> list[dict[str, Any]]:
    """Deterministic sample; with `key`, draws round-robin across strata so small subsets stay balanced."""
    rng = random.Random(seed)
    if key is None:
        return rng.sample(rows, min(size, len(rows)))
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strata[key(row)].append(row)
    for members in strata.values():
        rng.shuffle(members)
    sample: list[dict[str, Any]] = []
    while len(sample) < size and any(strata.values()):
        for name in sorted(strata):
            if strata[name] and len(sample) < size:
                sample.append(strata[name].pop())
    return sample
