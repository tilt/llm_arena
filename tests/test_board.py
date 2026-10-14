"""The claims board's pure core: witness ledger, integrity, ranking and the overall leaderboard."""

from __future__ import annotations

from typing import Any

import pytest

from llm_arena.board import (
    BoardIntegrityError,
    GistState,
    LedgerLine,
    Registry,
    RegistryEntry,
    Removal,
    Row,
    build,
    check_evidence,
    overall,
    rank_key,
    scenario_boards,
)
from llm_arena.claims import ClaimRole, canonical, check_claim
from llm_arena.conformance import _claim_fixture, _repro_body

NOW = "2026-10-12T06:00:00+00:00"
GIST = "a" * 32
REV = "b" * 40


def _claim() -> tuple[str, str, dict[str, Any]]:
    fixture = _claim_fixture()
    text = canonical(fixture)
    return text, check_claim(text).claim_hash, fixture


def _comment(cid: int, login: str, uid: int, body: str, *, edited: bool = False) -> dict[str, Any]:
    at = f"2026-10-11T10:{cid:02d}:00Z"
    return {"id": cid, "user": {"login": login, "id": uid}, "created_at": at,
            "updated_at": "2026-10-11T23:00:00Z" if edited else at, "body": body}  # fmt: skip


def _setup() -> tuple[Registry, dict[str, str], str, dict[str, Any]]:
    text, chash, fixture = _claim()
    entry = RegistryEntry(gist_id=GIST, revision=REV, claim_hash=chash, owner_login="alice", owner_id=1,
                          added_at="2026-10-11T09:00:00+00:00")  # fmt: skip
    return Registry(entries=[entry]), {chash: text}, chash, fixture


def _thread(chash: str, fixture: dict[str, Any], *rows: tuple[int, str, int, list[int]]) -> list[dict[str, Any]]:
    return [_comment(cid, login, uid, _repro_body(fixture, chash, passed)) for cid, login, uid, passed in rows]


def test_the_board_records_reproductions_once_and_ranks_the_claim() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]), (3, "alice", 1, [1, 1]))  # the author's own is recorded
    state = {chash: GistState(status="ok", comments=thread, total=2)}
    board, lines = build(registry, claims, [], state, now=NOW)
    assert [line.comment_id for line in lines] == [2, 3]
    row = board.scenarios[0].ranked[0]
    assert (row.people, row.tier, row.reproducers, row.cost_source) == (1, "reproduced", ["bob"], "reproduced")
    again, more = build(registry, claims, lines, state, now=NOW)
    assert more == [] and again.reproductions == 2


def test_a_reproduction_deleted_after_recording_still_counts_and_is_flagged() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]), (4, "carol", 3, [1, 0]))
    _, lines = build(registry, claims, [], {chash: GistState(status="ok", comments=thread, total=2)}, now=NOW)
    after = {chash: GistState(status="ok", comments=thread[1:], total=1)}  # the author deleted bob's
    row = build(registry, claims, lines, after, now=NOW)[0].scenarios[0].ranked[0]
    assert row.people == 2 and [(n.kind, n.count) for n in row.notes] == [("removed_after_recorded", 1)]


def test_an_edited_reproduction_counts_as_recorded_and_one_never_recorded_does_not() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]))
    _, lines = build(registry, claims, [], {chash: GistState(status="ok", comments=thread, total=1)}, now=NOW)
    edited = [{**thread[0], "updated_at": "2026-10-12T01:00:00Z"}]
    row = build(registry, claims, lines, {chash: GistState(status="ok", comments=edited, total=1)}, now=NOW)[0]
    assert row.scenarios[0].ranked[0].people == 1
    assert [n.kind for n in row.scenarios[0].ranked[0].notes] == ["edited_after_recorded"]
    unseen = _thread(chash, fixture, (9, "dave", 8, [1, 1]))
    unseen[0]["updated_at"] = "2026-10-12T01:00:00Z"  # edited before the board ever saw it: v1 rules, not counted
    fresh = build(registry, claims, [], {chash: GistState(status="ok", comments=unseen, total=1)}, now=NOW)[0]
    assert fresh.scenarios[0].unreproduced[0].people == 0


def test_a_deleted_gist_keeps_its_row_from_cache_and_ledger() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]))
    first, lines = build(registry, claims, [], {chash: GistState(status="ok", comments=thread, total=1)}, now=NOW)
    gone = build(registry, claims, lines, {chash: GistState(status="deleted")}, now=NOW, previous=first)[0]
    row = gone.scenarios[0].ranked[0]
    assert row.people == 1 and not row.runnable and [n.kind for n in row.notes] == ["gist_deleted"]
    failed = build(registry, claims, lines, {}, now="2026-10-12T12:00:00+00:00", previous=first)[0]
    stale = failed.scenarios[0].ranked[0]
    assert stale.refreshed_at == NOW and stale.notes[0].kind == "not_refreshed" and stale.runnable


def test_rewritten_evidence_fails_the_build() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]), (4, "carol", 3, [1, 1]))
    _, lines = build(registry, claims, [], {chash: GistState(status="ok", comments=thread, total=2)}, now=NOW)
    check_evidence((registry, lines[:1]), (registry, lines), claims)  # growing is fine
    with pytest.raises(BoardIntegrityError, match="ledger was rewritten"):
        check_evidence((registry, lines), (registry, lines[1:]), claims)
    forged = lines[0].model_copy(update={"repro": lines[1].repro.model_copy(update={"seen": [99]})})
    with pytest.raises(BoardIntegrityError, match="doesn't match its hash"):
        check_evidence((registry, []), (registry, [forged, lines[1]]), claims)
    with pytest.raises(BoardIntegrityError, match="registry was rewritten"):
        check_evidence((registry, []), (Registry(), []), claims)
    with pytest.raises(BoardIntegrityError, match="doesn't match its hash"):
        check_evidence((registry, []), (registry, []), {chash: claims[chash].replace('"seed":0', '"seed":1')})


def test_a_delisted_claim_leaves_the_board_and_is_listed_for_30_days() -> None:
    registry, claims, chash, _ = _setup()
    delisted = Registry(entries=registry.entries, removed=[Removal(claim_hash=chash, reason="spam",
                                                                   at="2026-10-01T00:00:00+00:00")])  # fmt: skip
    board = build(delisted, claims, [], {}, now=NOW)[0]
    assert board.claims == 0 and [d.reason for d in board.delisted] == ["spam"]
    assert build(delisted, claims, [], {}, now="2026-11-15T00:00:00+00:00")[0].delisted == []


# ---- ranking and overall over hand-made rows ---------------------------------------------------------------------
def _role(model: str) -> ClaimRole:
    return ClaimRole(provider="openai", model=model, max_tokens=512)


def _row(chash: str, *, scenario: str = "reflection_sql", rate: float, low: float, people: int,
         roles: dict[str, ClaimRole] | None = None, credit: float = 0.5) -> Row:  # fmt: skip
    return Row(gist_id=GIST, revision=REV, claim_hash=chash, owner="o", scenario=scenario, scenario_version="1",
               state="ok", roles=roles or {"generator": _role("gpt-4.1-mini")}, tier="claimed", people=people,
               rate=rate, low=low, high=1.0, tasks=10, step_credit=credit, cost_usd_per_task=0.0,
               cost_source="claimed", claimed_rate=rate, reproduce_usd=0.01, made_at="2026-10-11", refreshed_at=NOW)  # fmt: skip


def test_ranking_is_sample_aware_and_only_reproduced_claims_rank() -> None:
    small = _row("1" * 64, rate=1.0, low=0.74, people=1)  # 11 of 11
    large = _row("2" * 64, rate=0.95, low=0.89, people=2)  # 95 of 100
    forged = _row("3" * 64, rate=1.0, low=0.99, people=0)  # an author-written 500-task 100% claim
    [board] = scenario_boards([small, forged, large])
    assert [r.claim_hash[0] for r in board.ranked] == ["2", "1"]
    assert [r.claim_hash[0] for r in board.unreproduced] == ["3"]
    assert [h[0] for h in board.merged] == ["3", "2", "1"]  # the merged view ranks everything, marked by tier
    assert rank_key(_row("4" * 64, rate=0.9, low=0.8, people=1, credit=0.9)) < rank_key(
        _row("5" * 64, rate=0.9, low=0.8, people=1, credit=0.1)
    )


def test_overall_scores_models_against_the_best_setup_in_each_scenario() -> None:
    hard_best = _row("1" * 64, rate=0.60, low=0.5, people=1, roles={"generator": _role("x")})
    easy_best = _row("2" * 64, scenario="reflection_writing", rate=0.95, low=0.9, people=1,
                     roles={"writer": _role("z")})  # fmt: skip
    easy_worst = _row("3" * 64, scenario="reflection_writing", rate=0.85, low=0.8, people=1,
                      roles={"writer": _role("y")})  # fmt: skip
    entries = overall(scenario_boards([hard_best, easy_best, easy_worst]), "reproduced")
    order = [(e.model, round(e.score, 2)) for e in entries["all"]]
    assert order[:2] == [("x", 0.0), ("z", 0.0)] and order[-1] == ("y", -0.1)  # y's raw 85% doesn't lift it
    assert entries["all"][0].only_claim == 1  # x's setup is the only claim on reflection_sql
    # the critic falls back to the generator, so x also appears under Critique; writing roles under Writing
    assert [e.model for e in entries["critique"]] == ["x", "z", "y"]
    assert [e.model for e in entries["code"]] == ["x"] and {e.model for e in entries["writing"]} == {"y", "z"}


def test_the_merged_feed_includes_unreproduced_setups() -> None:
    waiting = _row("1" * 64, rate=0.9, low=0.8, people=0, roles={"generator": _role("w")})
    boards = scenario_boards([waiting])
    assert overall(boards, "reproduced")["all"] == []
    assert [e.model for e in overall(boards, "merged")["all"]] == ["w"]


def test_ledger_lines_validate_their_repro() -> None:
    with pytest.raises(ValueError):
        LedgerLine.model_validate({"gist_id": GIST, "claim_hash": "0" * 64, "comment_id": 1, "user_login": "x",
                                   "created_at": "t", "recorded_at": "t", "block_sha256": "0" * 64, "repro": {},
                                   "prev_sha256": "0" * 64})  # fmt: skip


def test_a_build_refuses_evidence_changed_since_the_last_build() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]))
    first, lines = build(registry, claims, [], {chash: GistState(status="ok", comments=thread, total=1)}, now=NOW)
    assert (first.ledger_lines, first.registry_entries) == (1, 1)
    renamed = Registry(entries=[registry.entries[0].model_copy(update={"owner_login": "mallory"})])
    with pytest.raises(BoardIntegrityError, match="registry no longer matches"):
        build(renamed, claims, lines, {}, now=NOW, previous=first)
    with pytest.raises(BoardIntegrityError, match="ledger no longer matches"):
        build(registry, claims, [], {}, now=NOW, previous=first)


def test_removals_need_a_full_timestamp_and_are_anchored_between_builds() -> None:
    registry, claims, chash, _ = _setup()
    with pytest.raises(ValueError, match="timestamp"):
        Removal(claim_hash=chash, reason="spam", at="2026-10-12")
    removed = Registry(entries=registry.entries,
                       removed=[Removal(claim_hash=chash, reason="spam", at="2026-10-01T00:00:00+00:00")])  # fmt: skip
    first = build(removed, claims, [], {}, now=NOW)[0]
    assert first.removed_entries == 1
    with pytest.raises(BoardIntegrityError, match="removed list no longer matches"):
        build(registry, claims, [], {}, now=NOW, previous=first)


def test_a_thread_with_a_skipped_page_accuses_nobody_but_a_read_prefix_still_flags_deletions() -> None:
    registry, claims, chash, fixture = _setup()
    thread = _thread(chash, fixture, (2, "bob", 7, [1, 1]), (4, "carol", 3, [1, 1]))
    _, lines = build(registry, claims, [], {chash: GistState(status="ok", comments=thread, total=2)}, now=NOW)
    # bob's comment sat on a page too large to read (a gap): unknown, not removed
    gap = GistState(status="ok", comments=thread[1:], total=150, gap=True)
    ranked = build(registry, claims, lines, {chash: gap}, now=NOW)[0].scenarios[0].ranked[0]
    assert ranked.people == 2 and [n.kind for n in ranked.notes] == ["partial_thread"]
    # read as an unbroken prefix of a long thread, a missing recorded comment below the newest one is a deletion
    prefix = GistState(status="ok", comments=thread[1:], total=400)
    ranked = build(registry, claims, lines, {chash: prefix}, now=NOW)[0].scenarios[0].ranked[0]
    assert [n.kind for n in ranked.notes] == ["removed_after_recorded", "partial_thread"]
    # a later reproduction that saw one on the unreadable page: no "removed before the board saw it"
    dave = [_comment(9, "dave", 5, _repro_body(fixture, chash, [1, 1], seen=[2]))]
    ranked = build(registry, claims, [], {chash: GistState(status="ok", comments=dave, total=150, gap=True)},
                   now=NOW)[0].scenarios[0].ranked[0]  # fmt: skip
    assert [n.kind for n in ranked.notes] == ["partial_thread"]
