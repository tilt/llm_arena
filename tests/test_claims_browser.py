"""The Pages engine's claim methods: everything runs on bundles the page keeps (IndexedDB), with fake fetch."""

from __future__ import annotations

import json

import pytest

from llm_arena.core.errors import ConfigError
from test_browser_arena import EXPERIMENT, _arena


async def test_a_pages_run_is_shared_beaten_and_posted_from_bundles() -> None:
    arena, _, _ = _arena()
    arena.set_key("openai", "sk-test")
    await arena.models(refresh=True)
    mine = {**EXPERIMENT, "configs": [{"name": "nano", "roles": {"*": "openai:gpt-4.1-nano#max_tokens=512"}}]}
    await arena.service.wait(await arena.start_run(json.dumps({"experiment": mine, "run_id": "mine"})))
    bundle = arena.bundle("mine")
    draft = json.loads(arena.claim_draft(bundle, json.dumps({"names": {}})))
    assert draft["reasons"] == [] and json.loads(draft["claim_json"])["result"]["engine"] == "pages"
    claim = draft["claim_json"]
    check = json.loads(arena.claim_check(claim))
    assert check["state"] == "ok" and check["claim_hash"] == draft["claim_hash"]

    candidates = json.loads(await arena.claim_candidates(json.dumps({"claim": claim, "role": "generator"})))
    assert candidates == [{"ref": "openai:gpt-4.1-nano", "problem": "same model as the claim (gpt-4.1-nano)"}]

    config = arena.claim_experiment(json.dumps({"claim": claim, "cap_usd": 0.5}))
    await arena.service.wait(await arena.start_run(json.dumps({"experiment": json.loads(config), "run_id": "beat"})))
    repro = json.loads(arena.repro_draft(arena.bundle("beat"), json.dumps({"claim": claim})))
    assert repro["block"] and repro["reasons"] == [] and repro["repro"]["variant"] is None
    stats = json.loads(
        arena.claim_thread(
            json.dumps(
                {
                    "claim": claim,
                    "author": "alice",
                    "comments": [
                        {
                            "id": 1,
                            "user": {"login": "bob"},
                            "created_at": "t",
                            "updated_at": "t",
                            "body": repro["block"],
                        }
                    ],
                }
            )
        )
    )
    assert stats["people"] == 1 and stats["rate"] == 1.0  # fmt: skip


def test_imported_bundles_are_validated_by_the_engine() -> None:
    arena, _, _ = _arena()
    with pytest.raises(ConfigError, match="not a run bundle"):
        arena.check_bundle(json.dumps({"trials": []}))
    with pytest.raises(ConfigError, match="not run rows"):
        arena.check_bundle(json.dumps({"run": {"run_id": "x"}, "trials": [{"trial_id": "t"}]}))
    bundle = {"run": {"run_id": "../escape"}, "summary": {"configs": [], "paired_tests": [], "ratings": {}},
              "trials": [], "scores": [], "battles": []}  # fmt: skip
    with pytest.raises(ConfigError, match="run id"):
        arena.check_bundle(json.dumps(bundle))
    bundle["run"]["run_id"] = "r1"
    assert json.loads(arena.check_bundle(json.dumps(bundle)))["run"]["run_id"] == "r1"
