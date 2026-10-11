"""Per-step results ("which steps worked") on claims and reproductions (claims board, section 1)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from llm_arena.claims import (
    ClaimError,
    Repro,
    Swap,
    canonical,
    check_claim,
    claim_experiment,
    parse_repro,
    payload,
    repro_comment,
    repro_from_run,
    validate_repro,
)
from test_claims import make_claim, run


async def test_a_claim_carries_each_pass_criterion_it_graded() -> None:
    check = await make_claim()
    criteria = check.claim.result.criteria
    assert criteria is not None and set(criteria) == {"final_correct"}
    assert all(c.graded == check.claim.result.trials and c.passed <= c.graded for c in criteria.values())
    assert criteria["final_correct"].passed == check.claim.result.passed


def _with_criteria(text: str, criteria: Any) -> str:
    claim = json.loads(text)
    claim["result"]["criteria"] = criteria
    return canonical(claim)


@pytest.mark.parametrize(
    ("criteria", "error"),
    [
        ({"made_up": {"passed": 1, "graded": 1}}, "no pass criteria"),
        ({"final_correct": {"passed": 2, "graded": 1}}, "don't fit"),
        ({"final_correct": {"passed": 1, "graded": 9}}, "don't fit"),
        ({"final_correct": {"passed": 1, "graded": 0}}, "greater than or equal to 1"),
        ({f"c{i}": {"passed": 0, "graded": 1} for i in range(17)}, "at most 16"),
    ],
)
async def test_hostile_per_step_results_are_refused(criteria: Any, error: str) -> None:
    check = await make_claim()
    with pytest.raises(ClaimError, match=error):
        check_claim(_with_criteria(canonical(payload(check.claim)), criteria))


async def test_a_reproduction_carries_per_step_results_and_partial_credit() -> None:
    check = await make_claim()
    beat = claim_experiment(check, local={}, swap=Swap(role="critic", candidate="openai:gpt-4.1-nano"), cap_usd=1.0,
                            gist=None, declared_names={})  # fmt: skip
    draft = repro_from_run(await run(beat), check, engine="local", arena_version="0.1.0")
    assert draft.block is not None and draft.repro is not None, draft.reasons
    for side in (draft.repro.baseline, draft.repro.variant):
        assert side is not None and side.partial is not None and side.criteria is not None
        assert side.criteria["final_correct"].graded == side.trials
    repro = parse_repro(draft.block)
    assert isinstance(repro, Repro) and validate_repro(check, repro) is None
    hostile = payload(repro)
    hostile["baseline"]["criteria"] = {"final_correct": {"passed": 5, "graded": 9}}
    assert "don't fit" in (validate_repro(check, Repro.model_validate(hostile)) or "")
    hostile["baseline"]["criteria"] = {"made_up": {"passed": 0, "graded": 1}}
    assert "no pass criteria" in (validate_repro(check, Repro.model_validate(hostile)) or "")


async def test_unset_post_v1_fields_stay_out_of_published_bytes() -> None:
    """A reproduction without the new fields is byte-identical to what v1 posted (no null keys)."""
    check = await make_claim()
    beat = claim_experiment(check, local={}, swap=None, cap_usd=1.0, gist=None, declared_names={})
    draft = repro_from_run(await run(beat), check, engine="local", arena_version="0.1.0")
    assert draft.repro is not None
    bare = draft.repro.model_copy(update={"baseline": draft.repro.baseline.model_copy(
        update={"criteria": None, "partial": None})})  # fmt: skip
    body = repro_comment(bare)
    assert '"criteria"' not in body and '"partial"' not in body
    claim = payload(check.claim)
    claim["result"].pop("criteria")
    assert "criteria" not in payload(check_claim(canonical(claim)).claim)["result"]
