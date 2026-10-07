"""LLM-as-judge: rubric scoring with structured verdicts, and position-swapped pairwise comparison.

Judges are models too, so they are configurable, pinned per experiment, reported separately
(their cost is not charged to the pipeline) and should be calibrated (see calibration.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from llm_arena.eval.base import EvalContext, Level, Score
from llm_arena.llm.client import LLMClient, structured, user
from llm_arena.llm.types import Message


class Criterion(BaseModel):
    name: str
    description: str
    weight: float = 1.0


class Rubric(BaseModel):
    name: str
    criteria: list[Criterion]
    pass_threshold: float = 0.7  # on the normalised 0–1 scale


class CriterionVerdict(BaseModel):
    criterion: str
    rationale: str = Field(description="One or two sentences citing the output")
    score: int = Field(ge=1, le=5, description="1 = fails the criterion, 5 = fully meets it")


class RubricVerdict(BaseModel):
    verdicts: list[CriterionVerdict]


class PairwiseVerdict(BaseModel):
    rationale: str
    winner: Literal["A", "B", "tie"]


_RUBRIC_SYSTEM = (
    "You are a strict, fair evaluator. Score the RESPONSE against each criterion on a 1-5 scale. "
    "Judge only what is written; do not reward length or confident tone. Reason briefly before each score."
)


async def judge_rubric(
    judge: LLMClient,
    rubric: Rubric,
    task_prompt: str,
    response: str,
    *,
    reference: str | None = None,
    images: list[bytes] | None = None,
) -> tuple[float, RubricVerdict]:
    """Return the weighted score normalised to [0, 1] and the per-criterion verdicts."""
    criteria = "\n".join(f"- {c.name}: {c.description}" for c in rubric.criteria)
    body = f"TASK:\n{task_prompt}\n\nRESPONSE:\n{response}\n\nCRITERIA:\n{criteria}"
    if reference:
        body += f"\n\nREFERENCE (facts the response should agree with):\n{reference}"
    messages: list[Message] = [{"role": "system", "content": _RUBRIC_SYSTEM}, user(body, list(images or []))]
    verdict, _ = await structured(judge, messages, RubricVerdict, temperature=0.0)
    return _normalise(rubric, verdict), verdict


def _normalise(rubric: Rubric, verdict: RubricVerdict) -> float:
    by_name = {v.criterion.strip().lower(): v.score for v in verdict.verdicts}
    total_weight = sum(c.weight for c in rubric.criteria)
    # A criterion the judge skipped scores the minimum: silence must not inflate the score.
    weighted = sum(c.weight * (by_name.get(c.name.lower(), 1) - 1) / 4 for c in rubric.criteria)
    return weighted / total_weight if total_weight else 0.0


async def judge_pairwise(
    judge: LLMClient, task_prompt: str, response_a: str, response_b: str, criteria: str
) -> tuple[Literal["a", "b", "tie"], str]:
    """Compare twice with positions swapped; disagreement between the two orders counts as a tie.

    This cancels the judge's position bias instead of letting it pick winners.
    """
    first = await _compare(judge, task_prompt, response_a, response_b, criteria)
    second = await _compare(judge, task_prompt, response_b, response_a, criteria)
    swapped_back = {"A": "B", "B": "A", "tie": "tie"}[second.winner]
    if first.winner == swapped_back and first.winner != "tie":
        return ("a" if first.winner == "A" else "b"), first.rationale
    return "tie", f"order-dependent or tied verdicts ({first.winner} / {second.winner}): {first.rationale}"


async def _compare(judge: LLMClient, task_prompt: str, a: str, b: str, criteria: str) -> PairwiseVerdict:
    messages: list[Message] = [
        {
            "role": "system",
            "content": "Compare two responses to the same task. Ignore length and order. "
            "Answer 'tie' when neither is clearly better.",
        },
        {
            "role": "user",
            "content": f"TASK:\n{task_prompt}\n\nCRITERIA:\n{criteria}\n\nRESPONSE A:\n{a}\n\nRESPONSE B:\n{b}",
        },
    ]
    verdict, _ = await structured(judge, messages, PairwiseVerdict, temperature=0.0)
    return verdict


@runtime_checkable
class JudgeEvaluator(Protocol):
    """An evaluator whose scores need a judge model (so they cannot be recomputed offline, see runner/regrade.py)."""

    def owns(self, score_name: str) -> bool: ...


@dataclass
class RubricJudgeEvaluator:
    """Evaluator adapter: scores `ctx.output.final` with a rubric; emits overall + per-criterion scores."""

    rubric: Rubric
    level: Level = "e2e"
    reference_key: str | None = None  # task.data key holding reference facts
    include_artifacts: bool = False  # send PNG artifacts to a vision-capable judge

    @property
    def name(self) -> str:
        return f"judge:{self.rubric.name}"

    def owns(self, score_name: str) -> bool:
        """Whether a score comes from this judge (the rubric's overall score or one of its criteria)."""
        return score_name == self.rubric.name or score_name.startswith(f"{self.rubric.name}.")

    async def evaluate(self, ctx: EvalContext) -> list[Score]:
        if ctx.judge is None:
            return []
        reference = ctx.task.data.get(self.reference_key) if self.reference_key else None
        images = (
            [data for key, data in ctx.output.artifacts.items() if key.endswith(".png")]
            if self.include_artifacts
            else None
        )
        value, verdict = await judge_rubric(
            ctx.judge,
            self.rubric,
            ctx.task.prompt,
            ctx.output.final,
            reference="\n".join(reference) if isinstance(reference, list) else reference,
            images=images,
        )
        scores = [
            Score(
                name=self.rubric.name,
                value=value,
                level=self.level,
                passed=value >= self.rubric.pass_threshold,
                rationale="; ".join(f"{v.criterion}={v.score}" for v in verdict.verdicts),
            )
        ]
        scores += [
            Score(
                name=f"{self.rubric.name}.{v.criterion}",
                value=(v.score - 1) / 4,
                level=self.level,
                rationale=v.rationale,
            )
            for v in verdict.verdicts
        ]
        return scores
