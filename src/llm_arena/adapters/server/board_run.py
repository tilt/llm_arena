"""One board run, as the board workflow does it: answer submissions, read every listed gist, build, write board-data.

`run` reads the `board-data` checkout, sweeps open submission issues (deciding, not yet answering them), reads each
listed gist's head and comment pages, builds the board and the new ledger lines, checks that no evidence was
rewritten, and writes the files. Issue answers are returned as actions and sent by `notify` only after the workflow
pushed the branch, so a failed push leaves every submission open for the next sweep.

Failures (design §3-§4): a claim's own problems reject its submission; a timeout or 5xx on one gist is retried once
and then counts against that issue or row only; a missing or refused token or a spent rate limit stops the whole run
before anything is written.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from llm_arena.adapters.server.gists import MAX_PAGES, PER_PAGE, GistClient, GistFailure
from llm_arena.adapters.server.github_issues import ACCEPTED, INTERNAL, REJECTED, RETRY, RETRY_MARK, IssueClient
from llm_arena.board import (
    DAILY_LIMIT,
    MAX_ATTEMPTS,
    SUBMISSION_LABEL,
    Board,
    GistState,
    LedgerLine,
    Registry,
    RegistryEntry,
    admit,
    build,
    check_evidence,
    line_text,
    parse_submission,
)
from llm_arena.claims import canonical, check_claim

MAX_BOARD_BYTES = 2 * 1024 * 1024
BUDGET_MARGIN = 100
MAX_FAILING_SHARE = 0.2
GLOBAL_KINDS = frozenset({"unauthorized", "rate_limited", "throttled"})


class RunStopped(RuntimeError):
    """A failure that isn't any one claim's or issue's: stop, write nothing, keep the published board."""


class Action(BaseModel):
    issue: int
    kind: Literal["accept", "reject", "retry", "internal_error"]
    text: str


@dataclass
class RunResult:
    board: Board
    actions: list[Action] = field(default_factory=list)
    new_lines: int = 0
    added: list[str] = field(default_factory=list)


# ---- board-data on disk ------------------------------------------------------------------------------------------
@dataclass
class BoardData:
    root: Path

    @property
    def dir(self) -> Path:
        return self.root / "board"

    def registry(self) -> Registry:
        path = self.dir / "registry.json"
        return Registry.model_validate_json(path.read_text()) if path.exists() else Registry()

    def claims(self) -> dict[str, str]:
        folder = self.dir / "claims"
        return {p.stem: p.read_text() for p in sorted(folder.glob("*.json"))} if folder.exists() else {}

    def ledger(self) -> list[LedgerLine]:
        path = self.dir / "ledger.jsonl"
        if not path.exists():
            return []
        return [LedgerLine.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]

    def previous(self) -> Board | None:
        path = self.dir / "board.json"
        try:
            return Board.model_validate_json(path.read_text()) if path.exists() else None
        except ValueError:
            return None  # an older board format: rebuild from the evidence

    def write(self, registry: Registry, claims: dict[str, str], ledger: list[LedgerLine], board: Board) -> None:
        text = board.model_dump_json()
        if len(text.encode()) > MAX_BOARD_BYTES:
            raise RunStopped("board.json would be larger than 2 MB")
        (self.dir / "claims").mkdir(parents=True, exist_ok=True)
        for chash, claim in claims.items():
            path = self.dir / "claims" / f"{chash}.json"
            if not path.exists():
                path.write_text(claim)
        (self.dir / "registry.json").write_text(registry.model_dump_json(indent=1) + "\n")
        (self.dir / "ledger.jsonl").write_text("".join(f"{line_text(x)}\n" for x in ledger))
        (self.dir / "board.json").write_text(text)


# ---- the run -----------------------------------------------------------------------------------------------------
def _stop_if_global(failure: GistFailure) -> None:
    if failure.kind in GLOBAL_KINDS:
        raise RunStopped(f"GitHub refused the board's reads ({failure.kind}): {failure} — check BOARD_READ_TOKEN")


def _guard(gists: GistClient, needed: int) -> None:
    """Stop before the token's hourly budget runs out (it's shared with anything else that account runs)."""
    if gists.remaining is not None and gists.remaining < needed + BUDGET_MARGIN:
        raise RunStopped(f"only {gists.remaining} GitHub requests left this hour; the next run continues")


async def _read_thread(gists: GistClient, entry: RegistryEntry) -> GistState:
    """Head plus only the comment pages it needs; one retry on a timeout or 5xx, then this row fails alone."""
    for attempt in (1, 2):
        try:
            head = await gists.head(entry.gist_id)
            pages = min(MAX_PAGES, math.ceil(head["comments"] / PER_PAGE))
            comments = [c for page in range(1, pages + 1) for c in await gists.comments(entry.gist_id, page)]
            return GistState(status="ok", comments=comments, total=head["comments"])
        except GistFailure as failure:
            if failure.kind == "not_found":
                return GistState(status="deleted")
            _stop_if_global(failure)
            if attempt == 2 or failure.kind not in {"unreachable", "server"}:
                return GistState(status="failed", reason=str(failure))
    return GistState(status="failed", reason="unreachable")  # pragma: no cover (the loop always returns)


async def _sweep(
    registry: Registry, claims: dict[str, str], gists: GistClient, issues: IssueClient, now: str
) -> tuple[Registry, list[Action], list[str]]:
    """Decide every open submission. Nothing is answered here; accepted claims join the registry and the cache."""
    actions: list[Action] = []
    added: list[str] = []
    since = (datetime.fromisoformat(now) - timedelta(days=1)).isoformat()
    for issue in await issues.open_submissions(SUBMISSION_LABEL):
        number = issue["number"]
        submission = parse_submission(issue["body"])
        if isinstance(submission, str):
            actions.append(Action(issue=number, kind="reject", text=submission))
            continue
        if await issues.recent_count(SUBMISSION_LABEL, issue["user_login"], since) >= DAILY_LIMIT:
            actions.append(Action(issue=number, kind="reject",
                                  text=f"at most {DAILY_LIMIT} submissions per person per day; try again tomorrow"))  # fmt: skip
            continue
        _guard(gists, len(registry.entries) * (1 + MAX_PAGES) + 2)
        try:
            found = await gists.claim(submission.gist_id, submission.revision)
        except GistFailure as failure:
            _stop_if_global(failure)
            if failure.kind in {"not_found", "invalid"}:
                actions.append(
                    Action(issue=number, kind="reject", text=f"the gist can't be read as a claim: {failure}")
                )
                continue
            attempts = await issues.attempts(number) + 1
            kind: Literal["retry", "internal_error"] = "internal_error" if attempts >= MAX_ATTEMPTS else "retry"
            actions.append(Action(issue=number, kind=kind, text=str(failure)))
            continue
        result = admit(registry, found["claim"], submission, owner_login=found["owner"], owner_id=found["owner_id"],
                       submitter_id=issue["user_id"], issue=number, now=now)  # fmt: skip
        if isinstance(result, str):
            actions.append(Action(issue=number, kind="reject", text=result))
            continue
        registry = Registry(entries=[*registry.entries, result], removed=registry.removed)
        claims[result.claim_hash] = found["claim"]
        added.append(result.claim_hash)
        scenario = check_claim(found["claim"]).claim.scenario
        actions.append(Action(issue=number, kind="accept",
                              text=f"Added to the claims board ({scenario}). It shows after this build is deployed, "
                                   f"usually within minutes."))  # fmt: skip
    return registry, actions, added


async def run(
    data: BoardData, gists: GistClient, issues: IssueClient | None, *, now: str, offline: bool = False
) -> RunResult:
    before = (data.registry(), data.ledger())
    claims = data.claims()
    registry: Registry = before[0]
    actions: list[Action] = []
    added: list[str] = []
    if issues is not None and not offline:
        registry, actions, added = await _sweep(registry, claims, gists, issues, now)
    threads: dict[str, GistState] = {}
    if not offline:
        removed = {r.claim_hash for r in registry.removed}
        listed = [e for e in registry.entries if e.claim_hash not in removed]
        for i, entry in enumerate(listed):
            _guard(gists, (len(listed) - i) * (1 + MAX_PAGES))
            threads[entry.claim_hash] = await _read_thread(gists, entry)
        failing = sum(state.status == "failed" for state in threads.values())
        if listed and failing / len(listed) > MAX_FAILING_SHARE:
            raise RunStopped(f"{failing} of {len(listed)} gists couldn't be read; keeping the published board")
    board, lines = build(registry, claims, before[1], threads, now=now, previous=data.previous())
    after = (registry, [*before[1], *lines])
    check_evidence(before, after, claims)
    data.write(registry, claims, after[1], board)
    return RunResult(board=board, actions=actions, new_lines=len(lines), added=added)


# ---- answering submissions after the push -------------------------------------------------------------------------
_ANSWERS = {
    "accept": (ACCEPTED, "completed"),
    "reject": (REJECTED, "not_planned"),
    "internal_error": (INTERNAL, "not_planned"),
}


async def notify(actions: list[Action], issues: IssueClient) -> None:
    for action in actions:
        if action.kind == "retry":
            await issues.comment(action.issue, f"{RETRY_MARK}\nThe board couldn't read the claim this time "
                                               f"({action.text}). It will retry on the next run.")  # fmt: skip
            await issues.label(action.issue, [RETRY])
            continue
        label, reason = _ANSWERS[action.kind]
        prefix = {"accept": "", "reject": "Not added: ",
                  "internal_error": "The board kept failing to read this claim: "}[action.kind]  # fmt: skip
        suffix = (
            " Please resubmit; this doesn't count toward your daily limit." if action.kind == "internal_error" else ""
        )
        await issues.comment(action.issue, f"{prefix}{action.text}{suffix}")
        await issues.label(action.issue, [label])
        await issues.close(action.issue, reason)  # type: ignore[arg-type]


def dump_actions(actions: list[Action]) -> str:
    return canonical([a.model_dump() for a in actions])


def load_actions(text: str) -> list[Action]:
    return [Action.model_validate(row) for row in json.loads(text or "[]")]
