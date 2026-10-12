"""The claims board: listed claims ranked per scenario, with a witness ledger and an overall model leaderboard.

Everything here is pure: the caller reads GitHub and the `board-data` branch, this module decides. It counts with the
same rules the claim page uses (`check_claim`, `validate_repro`, `trust_stats`), plus one thing the claim page can't
do: a ledger of every valid reproduction the board has seen, so a reproduction the gist author deletes later still
counts and is flagged instead of vanishing.

- Ranking (design doc §5): only claims with at least one counted reproduction by someone else are ranked, by the low
  end of their task-level interval, then step credit, people and date. Unreproduced claims wait in their own list.
- Integrity (§2, eng D10): the registry, the removed list and the ledger only ever grow, the ledger is hash-chained,
  and every cached claim must match its hash. A build that would break one of these refuses to write anything.
- Overall (design 5A, eng D7/D8): models across scenarios by role group, scored by their mean gap to the best setup
  in each scenario, so being tried on an easy scenario doesn't lift a model.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_arena.claims import (
    ClaimCheck,
    ClaimError,
    ClaimRole,
    ClaimState,
    Comment,
    Repro,
    StepResult,
    called_roles,
    canonical,
    check_claim,
    check_decisions,
    claim_hash,
    parse_claim,
    parse_repro,
    payload,
    repro_comment,
    task_interval,
    task_shares,
    trust_stats,
    validate_repro,
)
from llm_arena.decisions.config import DecisionConfig
from llm_arena.scenarios.base import SCENARIOS, RoleRequirement, Scenario, get_scenario

BOARD_VERSION = 1
MAX_REGISTRY = 200
DELISTED_DAYS = 30
VERIFIED_PEOPLE = 3  # the claim page's threshold for its "above the interval" note
GENESIS = "0" * 64
_HEX64 = r"^[0-9a-f]{64}$"
_GIST_ID = r"^[0-9a-f]{20,32}$"
_REVISION = r"^[0-9a-f]{40}$"

Tier = Literal["claimed", "reproduced", "verified"]
Feed = Literal["reproduced", "merged"]
RoleGroup = Literal["all", "tool_calling", "code", "writing", "critique", "planning", "vision", "decision"]
NoteKind = Literal[
    "removed_after_recorded", "edited_after_recorded", "removed_referenced", "gist_deleted", "not_refreshed",
    "not_runnable", "partial_thread",
]  # fmt: skip
FEEDS: tuple[Feed, ...] = ("reproduced", "merged")
GROUPS: tuple[RoleGroup, ...] = ("all", "tool_calling", "code", "writing", "critique", "planning", "vision", "decision")


class BoardIntegrityError(ValueError):
    """The board's evidence was rewritten or doesn't match its hashes. The build writes nothing."""


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- what board-data stores ------------------------------------------------------------------------------------
class RegistryEntry(_Closed):
    gist_id: str = Field(pattern=_GIST_ID)
    revision: str = Field(pattern=_REVISION)
    claim_hash: str = Field(pattern=_HEX64)
    owner_login: str = Field(max_length=100)
    owner_id: int | None = Field(default=None, ge=1)
    submitted_by_id: int | None = Field(default=None, ge=1)
    issue: int | None = Field(default=None, ge=1)
    added_at: str = Field(max_length=40)


class Removal(_Closed):
    """A delisting, written by hand on board-data: `at` is a full timestamp such as 2026-10-12T00:00:00+00:00."""

    claim_hash: str = Field(pattern=_HEX64)
    reason: str = Field(min_length=1, max_length=200)
    at: str = Field(max_length=40)

    @field_validator("at")
    @classmethod
    def _timestamp(cls, value: str) -> str:
        try:
            aware = datetime.fromisoformat(value).tzinfo is not None
        except ValueError:
            aware = False
        if not aware:
            raise ValueError(
                f"needs a full timestamp with its time zone, such as 2026-10-12T00:00:00+00:00 ({value!r})"
            )
        return value


class Registry(_Closed):
    entries: list[RegistryEntry] = Field(default_factory=list, max_length=MAX_REGISTRY)
    removed: list[Removal] = Field(default_factory=list)


class LedgerLine(_Closed):
    """One reproduction the board recorded, with its validated block, so it outlives the comment."""

    gist_id: str = Field(pattern=_GIST_ID)
    claim_hash: str = Field(pattern=_HEX64)
    comment_id: int = Field(ge=1)
    user_login: str = Field(max_length=100)
    user_id: int | None = Field(default=None, ge=1)
    created_at: str = Field(max_length=40)
    recorded_at: str = Field(max_length=40)
    block_sha256: str = Field(pattern=_HEX64)
    repro: Repro
    prev_sha256: str = Field(pattern=_HEX64)


def line_text(line: LedgerLine) -> str:
    return canonical(payload(line))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---- what the adapter hands in per claim -----------------------------------------------------------------------
class GistState(BaseModel):
    """A claim's gist as the build found it: read (with its thread), deleted (404), or not readable this time."""

    status: Literal["ok", "deleted", "failed"]
    comments: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    reason: str = ""
    transient: bool = Field(default=False, description="GitHub's trouble (timeout, 5xx), not the gist's own")


# ---- the published board ---------------------------------------------------------------------------------------
class RowNote(BaseModel):
    kind: NoteKind
    count: int = 0
    detail: str = ""


class Row(BaseModel):
    gist_id: str
    revision: str
    claim_hash: str
    owner: str
    scenario: str
    scenario_version: str
    state: ClaimState
    runnable: bool = True
    roles: dict[str, ClaimRole]
    decisions: dict[str, Any] | None = None
    judge: ClaimRole | None = None
    tier: Tier
    people: int
    reproducers: list[str] = Field(default_factory=list, description="logins of the counted reproducers")
    rate: float
    low: float
    high: float
    tasks: int
    step_credit: float
    criteria: dict[str, StepResult] | None = None
    cost_usd_per_task: float
    cost_source: Literal["claimed", "reproduced"]
    claimed_rate: float
    reproduce_usd: float = Field(description="about this much to reproduce the claimed setup once")
    made_at: str
    refreshed_at: str
    notes: list[RowNote] = Field(default_factory=list)


class ScenarioBoard(BaseModel):
    scenario: str
    version: str
    ranked: list[Row] = Field(default_factory=list, description="claims reproduced by someone else, best first")
    unreproduced: list[Row] = Field(default_factory=list, description="waiting for a first reproduction")
    merged: list[str] = Field(default_factory=list, description="claim hashes of both lists in one ranking")
    older: list[Row] = Field(default_factory=list, description="made on an older scenario version")


class OverallEntry(BaseModel):
    provider: str
    model: str
    reasoning_effort: str | None = None
    tool_mode: str = "native"
    score: float = Field(description="mean gap to the best setup in each scenario (0 = always the best)")
    raw: float = Field(description="mean performance of its setups")
    setups: int
    scenarios: int
    only_claim: int = Field(description="setups that are the only claim in their scenario")
    claims: list[str] = Field(default_factory=list, description="claim hashes it appears in")


class Delisted(BaseModel):
    claim_hash: str
    scenario: str
    reason: str
    at: str


class Board(BaseModel):
    board_version: int = BOARD_VERSION
    built_at: str
    claims: int
    reproductions: int
    scenarios: list[ScenarioBoard] = Field(default_factory=list)
    overall: dict[Feed, dict[RoleGroup, list[OverallEntry]]] = Field(default_factory=dict)
    delisted: list[Delisted] = Field(default_factory=list)
    ledger_lines: int = Field(default=0, description="ledger length at this build")
    ledger_head: str = Field(default=GENESIS, description="hash of the ledger's last line at this build")
    registry_entries: int = 0
    registry_head: str = Field(default=GENESIS, description="hash of the registry's entries at this build")
    removed_entries: int = 0
    removed_head: str = Field(default=GENESIS, description="hash of the removed list at this build")


# ---- integrity ---------------------------------------------------------------------------------------------------
def check_grows(name: str, before: Sequence[Any], after: Sequence[Any]) -> None:
    """`after` must start with exactly `before`: nothing edited, reordered or removed."""
    if len(after) < len(before) or list(after[: len(before)]) != list(before):
        raise BoardIntegrityError(f"{name} was rewritten: earlier entries changed or disappeared")


def check_chain(lines: Sequence[LedgerLine]) -> None:
    previous = GENESIS
    for line in lines:
        if line.prev_sha256 != previous:
            raise BoardIntegrityError(f"the ledger's hash chain breaks at comment {line.comment_id}")
        if line.block_sha256 != _sha(repro_comment(line.repro)):
            raise BoardIntegrityError(f"the ledger copy of comment {line.comment_id} doesn't match its hash")
        previous = _sha(line_text(line))


def check_cache(registry: Registry, claims: Mapping[str, str]) -> None:
    """Every listed claim has its cached copy, and the copy hashes to the registry's claim hash."""
    for entry in registry.entries:
        text = claims.get(entry.claim_hash)
        if text is None:
            raise BoardIntegrityError(f"no cached claim for {entry.claim_hash[:12]}")
        try:
            found = claim_hash(parse_claim(text))
        except ClaimError as exc:
            raise BoardIntegrityError(f"the cached claim {entry.claim_hash[:12]} doesn't parse: {exc}") from exc
        if found != entry.claim_hash:
            raise BoardIntegrityError(f"the cached claim {entry.claim_hash[:12]} doesn't match its hash")


def _registry_head(entries: Sequence[RegistryEntry | Removal]) -> str:
    return _sha(canonical([payload(e) for e in entries]))


def check_anchor(previous: Board, registry: Registry, ledger: Sequence[LedgerLine]) -> None:
    """The stored evidence still contains, unchanged, everything the last build recorded (its heads)."""
    n = previous.ledger_lines
    if len(ledger) < n or (n and _sha(line_text(ledger[n - 1])) != previous.ledger_head):
        raise BoardIntegrityError("the ledger no longer matches the last build: recorded reproductions were changed")
    m = previous.registry_entries
    if len(registry.entries) < m or (m and _registry_head(registry.entries[:m]) != previous.registry_head):
        raise BoardIntegrityError("the registry no longer matches the last build: listed claims were changed")
    k = previous.removed_entries
    if len(registry.removed) < k or (k and _registry_head(registry.removed[:k]) != previous.removed_head):
        raise BoardIntegrityError("the removed list no longer matches the last build: delistings were changed")


def check_evidence(
    before: tuple[Registry, Sequence[LedgerLine]], after: tuple[Registry, Sequence[LedgerLine]],
    claims: Mapping[str, str],
) -> None:  # fmt: skip
    """All of section 2's rules at once: registry, removed list and ledger only grow; chain and cache verify."""
    check_grows("the registry", before[0].entries, after[0].entries)
    check_grows("the removed list", before[0].removed, after[0].removed)
    check_grows("the ledger", [line_text(x) for x in before[1]], [line_text(x) for x in after[1]])
    check_chain(after[1])
    check_cache(after[0], claims)
    if len({e.claim_hash for e in after[0].entries}) != len(after[0].entries):
        raise BoardIntegrityError("a claim is listed twice")


# ---- one claim -------------------------------------------------------------------------------------------------
def _comment_of(line: LedgerLine) -> dict[str, Any]:
    """The recorded reproduction as an unedited comment, so the claim page's counting rules apply unchanged."""
    return {"id": line.comment_id, "user": {"login": line.user_login, "id": line.user_id},
            "created_at": line.created_at, "updated_at": line.created_at, "body": repro_comment(line.repro)}  # fmt: skip


def _check(text: str, expected_hash: str) -> tuple[ClaimCheck, str]:
    """The claim's check, or (when today's rules refuse it) a bare check plus why it can't be run here."""
    try:
        return check_claim(text), ""
    except ClaimError as exc:
        claim = parse_claim(text)
        return ClaimCheck(claim=claim, claim_hash=expected_hash, state="ok"), str(exc)


def record(
    entry: RegistryEntry, check: ClaimCheck, state: GistState, known: Iterable[int], now: str, previous: str
) -> list[LedgerLine]:
    """New ledger lines for the valid, unedited reproductions in this thread the board hasn't recorded yet."""
    seen = set(known)
    lines: list[LedgerLine] = []
    for raw in sorted(state.comments, key=lambda c: (str(c.get("created_at")), int(c.get("id") or 0))):
        try:
            comment = Comment.model_validate(raw)
        except ValueError:
            continue
        repro = parse_repro(comment.body)
        if (not isinstance(repro, Repro) or comment.id in seen or comment.updated_at != comment.created_at
                or validate_repro(check, repro) is not None):  # fmt: skip
            continue
        line = LedgerLine(
            gist_id=entry.gist_id, claim_hash=entry.claim_hash, comment_id=comment.id, user_login=comment.user,
            user_id=comment.user_id, created_at=comment.created_at, recorded_at=now,
            block_sha256=_sha(repro_comment(repro)), repro=repro, prev_sha256=previous,
        )  # fmt: skip
        lines.append(line)
        seen.add(comment.id)
        previous = _sha(line_text(line))
    return lines


def _merged_thread(state: GistState, recorded: Sequence[LedgerLine]) -> tuple[list[dict[str, Any]], list[RowNote]]:
    """The live thread with recorded copies standing in for deleted or edited comments."""
    by_id = {int(c.get("id") or 0): c for c in state.comments}
    partial = state.total > len(state.comments)
    newest = max(by_id, default=0)
    comments = [c for c in state.comments]
    removed = edited = 0
    for line in recorded:
        live = by_id.get(line.comment_id)
        if live is None:
            comments.append(_comment_of(line))
            # beyond the comments this build could read: still counted, but not known to be gone
            removed += state.status == "ok" and not (partial and line.comment_id > newest)
        elif live.get("updated_at") != live.get("created_at"):
            comments[comments.index(live)] = _comment_of(line)
            edited += 1
    notes = [RowNote(kind="removed_after_recorded", count=removed)] if removed else []
    notes += [RowNote(kind="edited_after_recorded", count=edited)] if edited else []
    return comments, notes


def claim_row(
    entry: RegistryEntry, text: str, recorded: Sequence[LedgerLine], state: GistState, *, now: str,
    previous: Row | None = None,
) -> Row:  # fmt: skip
    check, not_runnable = _check(text, entry.claim_hash)
    claim = check.claim
    notes: list[RowNote] = []
    if state.status == "ok":
        comments, notes = _merged_thread(state, recorded)
        total: int | None = state.total
        refreshed = now
    else:
        comments, total = [_comment_of(line) for line in recorded], None
        refreshed = previous.refreshed_at if previous else entry.added_at
        notes.append(RowNote(kind="gist_deleted") if state.status == "deleted"
                     else RowNote(kind="not_refreshed", detail=refreshed))  # fmt: skip
    if not_runnable:
        notes.append(RowNote(kind="not_runnable", detail=not_runnable))
    stats = trust_stats(check, comments, author=entry.owner_login, author_id=entry.owner_id, total=total)
    if stats.removed:
        notes.append(RowNote(kind="removed_referenced", count=stats.removed))
    if stats.partial:
        notes.append(RowNote(kind="partial_thread", count=stats.loaded, detail=str(stats.total)))
    bodies = {int(c.get("id") or 0): str(c.get("body") or "") for c in comments}
    counted = [r for r in stats.rows if r.status == "counted"]
    repros = [repro for r in counted if isinstance(repro := parse_repro(bodies.get(r.comment_id, "")), Repro)]
    rate, low, high = task_interval(task_shares(claim, repros))
    sides = [r.baseline for r in repros]
    trials = sum(s.trials for s in sides)
    credits = [s for s in sides if s.partial is not None]
    step_credit = (sum((s.partial or 0) * s.trials for s in credits) / sum(s.trials for s in credits)
                   if credits else claim.result.partial)  # fmt: skip
    criteria = claim.result.criteria
    if sides and all(s.criteria for s in sides):
        names = set.intersection(*(set(s.criteria or {}) for s in sides))
        criteria = {n: StepResult(passed=sum((s.criteria or {})[n].passed for s in sides),
                                  graded=sum((s.criteria or {})[n].graded for s in sides)) for n in sorted(names)} or None  # fmt: skip
    people = stats.people
    return Row(
        gist_id=entry.gist_id, revision=entry.revision, claim_hash=entry.claim_hash, owner=entry.owner_login,
        scenario=claim.scenario, scenario_version=claim.scenario_version, state=check.state,
        runnable=not not_runnable and state.status != "deleted", roles=dict(claim.setup.roles),
        decisions=claim.setup.decisions, judge=claim.judge,
        tier="verified" if people >= VERIFIED_PEOPLE else "reproduced" if people else "claimed", people=people,
        reproducers=[r.user for r in counted], rate=round(rate, 6), low=round(low, 6), high=round(high, 6),
        tasks=len(claim.tasks), step_credit=round(step_credit, 6), criteria=criteria,
        cost_usd_per_task=round(sum(s.cost_usd_per_task * s.trials for s in sides) / trials, 8) if trials
        else claim.result.cost_usd_per_task,
        cost_source="reproduced" if trials else "claimed", claimed_rate=claim.result.pass_rate,
        reproduce_usd=math.ceil(claim.result.cost_usd_per_task * len(claim.tasks) * claim.repeats * 100) / 100,
        made_at=claim.made_at, refreshed_at=refreshed, notes=notes,
    )  # fmt: skip


# ---- ranking -----------------------------------------------------------------------------------------------------
def rank_key(row: Row) -> tuple[float, float, int, str]:
    """Low end of the interval, then step credit, then people; ties go to the earlier claim."""
    return (-row.low, -row.step_credit, -row.people, row.made_at)


def scenario_boards(rows: Iterable[Row]) -> list[ScenarioBoard]:
    get_scenario("email_assistant")  # importing registers every scenario
    by_scenario: dict[str, list[Row]] = {}
    for row in rows:
        by_scenario.setdefault(row.scenario, []).append(row)
    boards = []
    for name in sorted(by_scenario):
        current = [r for r in by_scenario[name] if r.state == "ok"]
        older = sorted((r for r in by_scenario[name] if r.state != "ok"), key=rank_key)
        version = get_scenario(name).version if name in SCENARIOS else (current or older)[0].scenario_version
        ranked = sorted((r for r in current if r.people), key=rank_key)
        waiting = sorted((r for r in current if not r.people), key=rank_key)
        merged = [r.claim_hash for r in sorted(current, key=rank_key)]
        boards.append(ScenarioBoard(scenario=name, version=version, ranked=ranked, unreproduced=waiting,
                                    merged=merged, older=older))  # fmt: skip
    return boards


# ---- overall: models across scenarios by role group -------------------------------------------------------------
_KIND_GROUP: dict[str, RoleGroup] = {
    "agent": "tool_calling",
    "code": "code",
    "vision": "vision",
    "decision": "decision",
}


def role_group(requirement: RoleRequirement) -> RoleGroup:
    """Writing, Critique or Planning by a text role's skill; the other kinds map one to one."""
    if requirement.kind == "text":
        return requirement.skill or "writing"
    return _KIND_GROUP[requirement.kind]


def _resolve(setup_roles: Mapping[str, ClaimRole], scenario: Scenario, name: str) -> ClaimRole | None:
    """The model a role runs on: its own binding, else its fallback's (design: fallback roles count, eng R-2)."""
    by_name = {r.name: r for r in scenario.roles}
    seen: set[str] = set()
    while name not in setup_roles:
        fallback = by_name[name].fallback if name in by_name else None
        if fallback is None or fallback in seen:
            return None
        seen.add(name)
        name = fallback
    return setup_roles[name]


def used_models(row: Row) -> dict[RoleGroup, set[tuple[str, str, str | None, str]]]:
    """Per role group, the models this setup runs in a role of that group (called roles, fallbacks resolved)."""
    scenario = get_scenario(row.scenario)
    decisions: DecisionConfig | None
    try:
        decisions = check_decisions(scenario, row.decisions)
    except ClaimError:
        decisions = None
    used: dict[RoleGroup, set[tuple[str, str, str | None, str]]] = {}
    for requirement in scenario.roles:
        if requirement.name not in called_roles(scenario, decisions):
            continue
        role = _resolve(row.roles, scenario, requirement.name)
        if role is None:
            continue
        key = (role.provider, role.model, role.reasoning_effort, role.tool_mode)
        used.setdefault(role_group(requirement), set()).add(key)
        used.setdefault("all", set()).add(key)
    return used


def overall(boards: Sequence[ScenarioBoard], feed: Feed) -> dict[RoleGroup, list[OverallEntry]]:
    """Appearance tier: each model's mean gap to the best setup in each scenario it appears in (eng D8)."""
    gaps: dict[RoleGroup, dict[tuple[str, str, str | None, str], list[tuple[Row, float, bool]]]] = {}
    for board in boards:
        rows = board.ranked + (board.unreproduced if feed == "merged" else [])
        if not rows:
            continue
        best = max(r.rate for r in rows)
        alone = len(rows) == 1
        for row in rows:
            if row.scenario not in SCENARIOS:
                continue
            for group, models in used_models(row).items():
                for key in models:
                    gaps.setdefault(group, {}).setdefault(key, []).append((row, row.rate - best, alone))
    result: dict[RoleGroup, list[OverallEntry]] = {}
    for group in GROUPS:
        entries = []
        for (provider, model, effort, mode), items in gaps.get(group, {}).items():
            entries.append(OverallEntry(
                provider=provider, model=model, reasoning_effort=effort, tool_mode=mode,
                score=round(sum(g for _, g, _ in items) / len(items), 6),
                raw=round(sum(r.rate for r, _, _ in items) / len(items), 6), setups=len(items),
                scenarios=len({r.scenario for r, _, _ in items}), only_claim=sum(a for _, _, a in items),
                claims=[r.claim_hash for r, _, _ in items],
            ))  # fmt: skip
        result[group] = sorted(entries, key=lambda e: (-e.score, -e.setups, e.provider, e.model))
    return result


# ---- submissions ---------------------------------------------------------------------------------------------------
SUBMISSION_LABEL = "claim-submission"
DAILY_LIMIT = 5
MAX_ATTEMPTS = 3
_GIST_IN_TEXT = re.compile(r"(?:gist\.github\.com/[A-Za-z0-9-]{1,39}/|claim/gist/|\b)([0-9a-f]{32}|[0-9a-f]{20})\b")
_REVISION_IN_TEXT = re.compile(r"\b([0-9a-f]{40})\b")


class Submission(BaseModel):
    gist_id: str = Field(pattern=_GIST_ID)
    revision: str = Field(pattern=_REVISION)


def parse_submission(body: str) -> Submission | str:
    """The gist and pinned revision named in a submission issue (untrusted text), or why it names none."""
    text = body[:65_536]
    revision = _REVISION_IN_TEXT.search(text)
    if revision is None:
        return "the issue names no claim revision (use Submit to board on the claim page)"
    gist = _GIST_IN_TEXT.search(text.replace(revision.group(1), " "))
    if gist is None:
        return "the issue names no claim gist (use Submit to board on the claim page)"
    return Submission(gist_id=gist.group(1), revision=revision.group(1))


def admit(
    registry: Registry, claim_text: str, submission: Submission, *, owner_login: str, owner_id: int | None,
    submitter_id: int | None, issue: int, now: str,
) -> RegistryEntry | str:  # fmt: skip
    """A registry entry for a valid submission, or the reason it's refused (the claim's fault, never GitHub's)."""
    if len(registry.entries) >= MAX_REGISTRY:
        return f"the board is full ({MAX_REGISTRY} claims); the maintainer has been told"
    if owner_id is None or submitter_id != owner_id:
        return "only the gist's owner can submit it to the board"
    try:
        check = check_claim(claim_text)
    except ClaimError as exc:
        return f"this isn't a valid claim: {exc}"
    if check.state != "ok":
        return check.message or "this claim was made on another scenario version"
    if check.claim_hash in {r.claim_hash for r in registry.removed}:
        return "this claim was delisted from the board"
    if check.claim_hash in {e.claim_hash for e in registry.entries}:
        return "this claim is already on the board"
    return RegistryEntry(gist_id=submission.gist_id, revision=submission.revision, claim_hash=check.claim_hash,
                         owner_login=owner_login, owner_id=owner_id, submitted_by_id=submitter_id, issue=issue,
                         added_at=now)  # fmt: skip


# ---- the whole build ---------------------------------------------------------------------------------------------
def build(
    registry: Registry,
    claims: Mapping[str, str],
    ledger: Sequence[LedgerLine],
    threads: Mapping[str, GistState],
    *,
    now: str,
    previous: Board | None = None,
) -> tuple[Board, list[LedgerLine]]:
    """The board and the ledger lines to append. `threads` is keyed by claim hash; a missing one counts as failed."""
    check_chain(ledger)
    check_cache(registry, claims)
    if previous is not None:
        check_anchor(previous, registry, ledger)
    removed = {r.claim_hash: r for r in registry.removed}
    old_rows = {
        r.claim_hash: r
        for b in (previous.scenarios if previous else [])
        for r in [*b.ranked, *b.unreproduced, *b.older]
    }
    tail = _sha(line_text(ledger[-1])) if ledger else GENESIS
    new_lines: list[LedgerLine] = []
    rows: list[Row] = []
    delisted: list[Delisted] = []
    for entry in registry.entries:
        text = claims[entry.claim_hash]
        if entry.claim_hash in removed:
            gone = removed[entry.claim_hash]
            if datetime.fromisoformat(gone.at) >= datetime.fromisoformat(now) - timedelta(days=DELISTED_DAYS):
                delisted.append(Delisted(claim_hash=entry.claim_hash, scenario=parse_claim(text).scenario,
                                         reason=gone.reason, at=gone.at))  # fmt: skip
            continue
        state = threads.get(entry.claim_hash, GistState(status="failed", reason="not read"))
        mine = [line for line in [*ledger, *new_lines] if line.claim_hash == entry.claim_hash]
        if state.status == "ok":
            check, _ = _check(text, entry.claim_hash)
            fresh = record(entry, check, state, (x.comment_id for x in mine), now, tail)
            if fresh:
                new_lines += fresh
                tail = _sha(line_text(fresh[-1]))
                mine += fresh
        rows.append(claim_row(entry, text, mine, state, now=now, previous=old_rows.get(entry.claim_hash)))
    boards = scenario_boards(rows)
    board = Board(
        built_at=now, claims=len(rows), reproductions=len(ledger) + len(new_lines), scenarios=boards,
        overall={feed: overall(boards, feed) for feed in FEEDS}, delisted=delisted,
        ledger_lines=len(ledger) + len(new_lines),
        ledger_head=_sha(line_text([*ledger, *new_lines][-1])) if ledger or new_lines else GENESIS,
        registry_entries=len(registry.entries), registry_head=_registry_head(registry.entries),
        removed_entries=len(registry.removed), removed_head=_registry_head(registry.removed),
    )  # fmt: skip
    return board, new_lines


__all__ = [
    "BOARD_VERSION", "DAILY_LIMIT", "MAX_ATTEMPTS", "MAX_REGISTRY", "SUBMISSION_LABEL", "Board", "Submission",
    "admit", "parse_submission", "BoardIntegrityError", "Delisted", "GistState",
    "LedgerLine", "OverallEntry", "Registry", "RegistryEntry", "Removal", "Row", "RowNote", "ScenarioBoard",
    "build", "check_anchor", "check_cache", "check_chain", "check_evidence", "check_grows", "claim_row", "line_text", "overall",
    "rank_key", "record", "role_group", "scenario_boards", "used_models",
]  # fmt: skip
