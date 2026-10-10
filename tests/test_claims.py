"""Shareable claims: a run becomes a claim, Beat this re-runs it next to a variant, reproductions are tallied.

Runs use ScriptedLLM on `reflection_sql`; nothing needs a model server, a key or GitHub."""

from __future__ import annotations

import json
from typing import Any

import pytest

from llm_arena.claims import (
    CLAIMED_CONFIG,
    Claim,
    ClaimCheck,
    ClaimError,
    Repro,
    Swap,
    candidate_problem,
    check_claim,
    claim_experiment,
    claim_from_run,
    parse_repro,
    portable_setup,
    repro_comment,
    repro_from_run,
    setup_fingerprint,
    suggest_name,
    trust_stats,
    validate_repro,
    wilson,
)
from llm_arena.llm.client import LLMClient
from llm_arena.llm.registry import resolve_model
from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.memory_store import MemoryStore
from llm_arena.runner.ports import RunData, Runtime
from llm_arena.runner.rename import RenameRun, rename_data
from llm_arena.runner.run import ExperimentRunner

TASKS = ["harborview_march_rentals", "ebike_avg_minutes"]
GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
MINI = "openai:gpt-4.1-mini#max_tokens=1024"
SPECS = {
    "ollama:qwen3:14b": ModelSpec(name="ollama:qwen3:14b", provider="ollama", model="qwen3:14b"),
    "gpu-box:Qwen3-14B": ModelSpec(
        name="gpu-box:Qwen3-14B", provider="openai_compatible", model="Qwen3-14B", endpoint="gpu-box",
        endpoint_identity="abc123", base_url="http://10.0.0.2:8000/v1", input_cost_per_mtok=0, output_cost_per_mtok=0,
    ),
}  # fmt: skip


def factory(spec: ModelSpec) -> LLMClient:
    def reply(messages: list[dict[str, object]]) -> str:
        return '{"verdict": "accept", "issues": []}' if "verdict" in str(messages) else GOOD_SQL

    return ScriptedLLM([reply], spec=spec)


async def run(experiment: ExperimentConfig) -> RunData:
    store = MemoryStore()
    runner = ExperimentRunner(experiment, Runtime(client_factory=factory), store=store, model_specs=SPECS)
    await runner.run()
    return store.load_run()


def experiment(roles: dict[str, str], **extra: Any) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {"name": "mine", "scenarios": ["reflection_sql"], "task_ids": TASKS,
         "configs": [{"name": "mine", "roles": roles}], **extra}
    )  # fmt: skip


async def make_claim(roles: dict[str, str] | None = None, names: dict[str, str] | None = None) -> ClaimCheck:
    data = await run(experiment(roles or {"*": MINI}))
    draft = claim_from_run(data, names or {}, engine="local", made_at="2026-10-10T10:00:00", arena_version="0.1.0")
    assert draft.claim_json is not None, draft.reasons
    check = check_claim(draft.claim_json)
    assert check.claim_hash == draft.claim_hash
    return check


async def test_a_run_becomes_a_claim_that_validates() -> None:
    check = await make_claim()
    claim = check.claim
    assert check.state == "ok" and claim.scenario == "reflection_sql" and claim.repeats == 1
    assert [t.id for t in claim.tasks] == TASKS  # scenario order
    assert claim.setup.roles["generator"].provider == "openai" and claim.setup.roles["generator"].max_tokens == 1024
    assert claim.result.trials == 2 and claim.judge is None and check.swappable_roles == ["critic", "generator"]


async def test_beat_this_reproduces_the_claimed_setup_and_posts_a_valid_repro() -> None:
    check = await make_claim()
    swap = Swap(role="critic", candidate="openai:gpt-4.1-nano")
    beat = claim_experiment(check, local={}, swap=swap, cap_usd=1.0, gist=None, declared_names={})
    assert beat.budget_mode == "strict" and beat.claim_ref is not None
    variant = beat.configs[1]
    assert variant.compare_to == CLAIMED_CONFIG
    assert variant.roles["critic"] == "openai:gpt-4.1-nano#max_tokens=1024"  # inherits the replaced role's max_tokens
    runner = ExperimentRunner(beat, Runtime(client_factory=factory), model_specs=SPECS)
    claimed = [t for t in runner.plan() if t.config.name == CLAIMED_CONFIG]
    # The executed claimed setup is exactly the claim's (the core reproduction guarantee).
    assert {setup_fingerprint(portable_setup(t.setup, {})) for t in claimed} == {check.claim.setup_fp}
    data = await run(beat)
    draft = repro_from_run(data, check, engine="local", arena_version="0.1.0", seen=[5, 3])
    assert draft.block is not None, draft.reasons
    repro = parse_repro(draft.block)
    assert isinstance(repro, Repro) and repro.seen == [3, 5] and repro.variant is not None
    assert validate_repro(check, repro) is None
    # Renamed setups (any name, any order) still yield the same reproduction.
    renamed, _ = rename_data(data, RenameRun(configs={CLAIMED_CONFIG: "theirs", "swap-critic": "mine"}))
    again = repro_from_run(renamed, check, engine="local", arena_version="0.1.0", seen=[5, 3])
    assert again.block == draft.block


async def test_self_hosted_roles_travel_by_declared_name_and_match_any_server() -> None:
    check = await make_claim({"*": "ollama:qwen3:14b#max_tokens=512"}, {"ollama:qwen3:14b": "qwen3-14b"})
    role = check.claim.setup.roles["generator"]
    assert (role.provider, role.model) == ("self_hosted", "qwen3-14b")
    assert "gpu-box" not in check.claim.model_dump_json() and "10.0.0.2" not in check.claim.model_dump_json()
    assert check.claim.result.unpriced_roles == ["critic", "generator"]
    beat = claim_experiment(check, local={"generator": "gpu-box:Qwen3-14B", "critic": "gpu-box:Qwen3-14B"}, swap=None,
                            cap_usd=None, gist=None, declared_names={"gpu-box:Qwen3-14B": "qwen3-14b"})  # fmt: skip
    runner = ExperimentRunner(beat, Runtime(client_factory=factory), model_specs=SPECS)
    names = {"gpu-box:Qwen3-14B": "qwen3-14b"}
    assert {setup_fingerprint(portable_setup(t.setup, names)) for t in runner.plan()} == {check.claim.setup_fp}
    draft = repro_from_run(await run(beat), check, engine="pages", arena_version="0.1.0")
    assert draft.block is not None and draft.repro is not None and draft.repro.variant is None
    with pytest.raises(ClaimError, match="needs one of your models"):
        claim_experiment(check, local={}, swap=None, cap_usd=None, gist=None, declared_names={})


async def test_unclaimable_runs_list_every_reason() -> None:
    data = await run(experiment({"*": "openai:gpt-4.1-mini"}))  # no max_tokens
    draft = claim_from_run(data, {}, engine="local", made_at="t", arena_version="0")
    assert draft.claim_json is None and any("max_tokens" in reason for reason in draft.reasons)
    local = await run(experiment({"*": "ollama:qwen3:14b"}))
    draft = claim_from_run(local, {}, engine="local", made_at="t", arena_version="0")
    assert draft.self_hosted == ["ollama:qwen3:14b"] and "compare as" in draft.reasons[0]
    errored = RunData(run=data.run, trials=[{**data.trials[0], "status": "error"}, *data.trials[1:]],
                      scores=data.scores)  # fmt: skip
    assert any(
        "errored" in r for r in claim_from_run(errored, {}, engine="local", made_at="t", arena_version="0").reasons
    )


async def test_hostile_or_inconsistent_claims_are_refused() -> None:
    check = await make_claim()
    good = check.claim.model_dump(mode="json")

    def refused(mutate: Any, match: str) -> None:
        bad = json.loads(json.dumps(good))
        mutate(bad)
        with pytest.raises(ClaimError, match=match):
            check_claim(json.dumps(bad))

    refused(lambda c: c.update(extra="x"), "(?i)extra")
    refused(lambda c: c["setup"]["roles"]["generator"].update(base_url="http://evil"), "(?i)extra")
    refused(lambda c: c["setup"]["roles"]["generator"].update(provider="openai_compatible"), "provider")
    refused(lambda c: c["setup"]["params"].update(max_rounds=99), "setup_fp|param")
    refused(lambda c: c.update(result={**c["result"], "passed": 99}), "result")
    refused(lambda c: c.update(scenario="gsm8k"), "benchmark|unknown")
    refused(lambda c: c["tasks"][0].update(fp="00000000"), "task_fps_hash")
    with pytest.raises(ClaimError, match="256 KB"):
        check_claim(" " * (300 * 1024))
    research = Claim.model_validate({**good, "scenario": "research_report"})
    with pytest.raises(ClaimError):
        check_claim(research.model_dump_json())  # roles and params don't fit; never reaches a run


async def test_reproduction_rules_each_reject_their_case() -> None:
    check = await make_claim()
    beat = claim_experiment(check, local={}, swap=Swap(role="critic", candidate="openai:gpt-4.1-nano"), cap_usd=1.0,
                            gist=None, declared_names={})  # fmt: skip
    draft = repro_from_run(await run(beat), check, engine="local", arena_version="0.1.0")
    assert draft.repro is not None
    good = draft.repro.model_dump(mode="json")

    def reason(mutate: Any) -> str | None:
        bad = json.loads(json.dumps(good))
        mutate(bad)
        return validate_repro(check, Repro.model_validate(bad))

    assert reason(lambda r: None) is None
    assert "another version" in str(reason(lambda r: r.update(claim_hash="f" * 64)))
    assert "different tasks" in str(reason(lambda r: r.update(task_fps_hash="0" * 12)))
    assert "scenario version" in str(reason(lambda r: r.update(scenario_version="9")))
    assert "differs" in str(reason(lambda r: r["baseline"].update(setup_fp="0" * 12)))
    assert "judge" in str(reason(lambda r: r.update(judge={"provider": "openai", "model": "gpt-4.1-mini"})))
    assert "add up" in str(reason(lambda r: r["per_task"][0].update(b=0)))
    assert "errors" in str(reason(lambda r: r["baseline"].update(errors=1)))

    def two_roles(r: dict[str, Any]) -> None:
        r["variant"]["setup"]["roles"]["generator"]["model"] = "gpt-4.1-nano"
        from llm_arena.claims import ClaimSetup

        r["variant"]["setup_fp"] = setup_fingerprint(ClaimSetup.model_validate(r["variant"]["setup"]))

    assert "exactly one role" in str(reason(two_roles))


async def test_candidates_are_checked_by_the_engine() -> None:
    check = await make_claim()
    nano = resolve_model("openai:gpt-4.1-nano", {})
    assert candidate_problem(check, "critic", nano, engine="pages", names={}) is None
    assert "same model" in str(candidate_problem(check, "critic", resolve_model("openai:gpt-4.1-mini", {}),
                                                 engine="pages", names={}))  # fmt: skip
    assert "local app" in str(candidate_problem(check, "critic", SPECS["ollama:qwen3:14b"], engine="pages", names={}))
    assert candidate_problem(check, "critic", SPECS["ollama:qwen3:14b"], engine="local", names={}) is None
    assert candidate_problem(check, "critic", SPECS["gpu-box:Qwen3-14B"], engine="pages", names={}) is None
    unknown = ModelSpec(name="openai:mystery", provider="openai", model="mystery-1")
    assert "no known price" in str(candidate_problem(check, "critic", unknown, engine="local", names={}))
    blind = ModelSpec(name="x", provider="openai", model="gpt-4.1-nano", capabilities=Capabilities(tools=False))
    assert candidate_problem(check, "nonexistent", blind, engine="local", names={}) is not None


def test_suggested_names() -> None:
    assert suggest_name("qwen3:14b") == "qwen3-14b"
    assert suggest_name("Qwen/Qwen3-14B-AWQ") == "qwen3-14b-awq"
    assert suggest_name("///") == "model"


def _comment(cid: int, user: str, repro: Repro | None, *, edited: bool = False, at: str = "") -> dict[str, Any]:
    created = at or f"2026-10-10T10:{cid:02d}:00Z"
    return {"id": cid, "user": {"login": user}, "created_at": created,
            "updated_at": "2026-10-11T00:00:00Z" if edited else created,
            "body": repro_comment(repro) if repro else "nice claim!"}  # fmt: skip


def _repro(check: ClaimCheck, passed: list[int], **update: Any) -> Repro:
    n = len(check.claim.tasks)
    per_task = [{"b": b} for b in passed]
    base = {"setup_fp": check.claim.setup_fp, "passed": sum(passed), "trials": n, "errors": 0, "timeouts": 0,
            "budget_stopped": 0, "cost_usd_per_task": 0.001}  # fmt: skip
    data = {"arena_repro": 1, "claim_hash": check.claim_hash, "scenario_version": check.claim.scenario_version,
            "task_fps_hash": check.claim.task_fps_hash, "baseline": base, "per_task": per_task, "engine": "pages",
            "arena_version": "0.1.0", **update}  # fmt: skip
    return Repro.model_validate(data)


async def test_thread_tally_counts_latest_valid_non_author_reproduction() -> None:
    check = await make_claim()
    comments = [
        _comment(1, "alice", _repro(check, [1, 1])),  # the author
        _comment(2, "bob", _repro(check, [0, 0])),
        _comment(3, "bob", _repro(check, [1, 0])),  # bob's latest replaces his first
        _comment(4, "carol", _repro(check, [1, 1]), edited=True),
        _comment(5, "dave", _repro(check, [1, 1], claim_hash="e" * 64)),
        _comment(6, "erin", None),
    ]
    stats = trust_stats(check, comments, author="Alice")
    by_id = {row.comment_id: row.status for row in stats.rows}
    assert by_id == {1: "author", 2: "superseded", 3: "counted", 4: "edited", 5: "rejected"}
    assert stats.hidden == 1 and stats.people == 1 and (stats.passed, stats.trials) == (1, 2)
    assert stats.low is None  # below two people: no interval


async def test_above_interval_note_needs_three_people_and_a_full_thread() -> None:
    check = await make_claim()  # claimed 100% on 2 tasks
    repros = [[1, 1], [1, 0], [0, 1]]  # 100%, 50%, 50% -> 4/6 pooled
    comments = [_comment(10 + i, f"user{i}", _repro(check, p)) for i, p in enumerate(repros)]
    stats = trust_stats(check, comments, author="alice")
    low, high = wilson(4, 6)
    assert stats.people == 3 and (stats.low, stats.high) == (low, high)
    assert stats.above_interval is (check.claim.result.pass_rate > high)
    partial = trust_stats(check, comments, author="alice", total=400)
    assert partial.partial and not partial.above_interval and partial.loaded == 3


async def test_removed_reproductions_referenced_by_later_ones_are_reported() -> None:
    check = await make_claim()
    comments = [_comment(30, "bob", _repro(check, [1, 1], seen=[21, 22])), _comment(21, "carol", _repro(check, [1, 1]))]
    assert trust_stats(check, comments, author="alice").removed == 1  # 22 was deleted
    intact = [_comment(22, "dave", _repro(check, [1, 1])), *comments]
    assert trust_stats(check, intact, author="alice").removed == 0


def test_wilson_interval() -> None:
    low, high = wilson(24, 33)
    assert round(low, 2) == 0.56 and round(high, 2) == 0.85


def test_ref_settings_carry_max_tokens_and_no_temperature() -> None:
    spec = resolve_model("openai:gpt-4.1-mini#max_tokens=4096,temperature=none,reasoning=none", {})
    assert (spec.max_tokens, spec.temperature, spec.reasoning_effort) == (4096, None, "none")
    with pytest.raises(KeyError, match="max_tokens"):
        resolve_model("openai:gpt-4.1-mini#max_tokens=0", {})
    assert resolve_model("openai:gpt-4.1-mini#reasoning=low", {}).temperature == 0.2  # unchanged behavior


def test_setup_fingerprints_stay_what_they_were() -> None:
    """Regression (R6, R20): claims add a portable setup next to `setup_of`; existing fingerprints never change."""
    from llm_arena.runner.fingerprint import fingerprint, setup_of

    cloud = setup_of({"agent": resolve_model("openai:gpt-4.1-mini", {})}, {"max_turns": 8}, None)
    endpoint = setup_of({"agent": SPECS["gpu-box:Qwen3-14B"]}, {}, None)
    assert fingerprint(cloud) == "cd86194cb05d" and fingerprint(endpoint) == "67e4c09a49c8"
    assert "endpoint" in endpoint["roles"]["agent"]  # local setups keep the endpoint; only claims strip it


async def test_a_role_that_resolves_differently_here_is_refused_before_the_run() -> None:
    from llm_arena.service import ArenaService

    check = await make_claim()
    hot = {"openai:gpt-4.1-mini": ModelSpec(name="openai:gpt-4.1-mini", provider="openai", model="gpt-4.1-mini",
                                            backend="http")}  # fmt: skip
    service = ArenaService(Runtime(client_factory=factory), store_factory=lambda run_id: MemoryStore(), model_specs=hot)
    with pytest.raises(ClaimError, match="(critic|generator): .*default backend"):
        service.claim_experiment(check.claim.model_dump_json(), local={}, swap=None, cap_usd=1.0, gist=None,
                                 declared_names={})  # fmt: skip


async def test_a_judge_is_pinned_only_where_a_judge_grades() -> None:
    check = await make_claim()
    judged = check.claim.model_copy(update={"judge": check.claim.setup.roles["critic"]})
    with pytest.raises(ClaimError, match="no judge-graded"):
        check_claim(judged.model_dump_json())
