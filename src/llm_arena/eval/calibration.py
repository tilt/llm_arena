"""Judge calibration: compare a judge's pass/fail against hand labels (raw agreement + Cohen's κ).

Calibration sets live in data/calibration/<rubric>.jsonl with fields
  {"task": ..., "response": ..., "label": "pass" | "fail", "reference": optional}
Label a few dozen outputs by hand once; rerun calibration whenever the judge model changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from llm_arena.eval.judge import Rubric, judge_rubric
from llm_arena.eval.metrics import cohen_kappa
from llm_arena.llm.client import LLMClient

KAPPA_WARNING_THRESHOLD = 0.6  # below this, treat the judge's scores as indicative only


@dataclass
class CalibrationReport:
    rubric: str
    judge: str
    n: int
    agreement: float
    kappa: float
    confusion: dict[str, int]  # keys like "human=pass,judge=fail"

    @property
    def trustworthy(self) -> bool:
        return self.kappa >= KAPPA_WARNING_THRESHOLD


async def calibrate(judge: LLMClient, rubric: Rubric, examples_path: Path) -> CalibrationReport:
    examples = [json.loads(line) for line in examples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    human, machine = [], []
    for example in examples:
        value, _ = await judge_rubric(
            judge, rubric, example["task"], example["response"], reference=example.get("reference")
        )
        human.append(example["label"])
        machine.append("pass" if value >= rubric.pass_threshold else "fail")
    confusion: dict[str, int] = {}
    for h, m in zip(human, machine, strict=True):
        key = f"human={h},judge={m}"
        confusion[key] = confusion.get(key, 0) + 1
    agreement = sum(h == m for h, m in zip(human, machine, strict=True)) / len(human)
    return CalibrationReport(
        rubric.name, judge.spec.name, len(human), agreement, cohen_kappa(human, machine), confusion
    )
