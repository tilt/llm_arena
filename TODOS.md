# TODOS

## Claims

### v1.1: claim evidence format and in-browser regrade

**What:** Design one redacted, typed evidence format for shared claims, then use it to re-enable trace inspection on
claims and in-browser regrading of grading-only scenario drift (with per-version reproduction groups).

**Why:** v1 claims publish setup and results only, so visitors can't step through the claimed run, and a claim freezes
read-only whenever its scenario's grading changes.

**Context:** Deferred by the eng review of `docs/designs/shareable-claims.md` (D1: regrade; D13: `bundle.json`; the
memory-only bundle validation of D3 is carried over unchanged). Raw run bundles were rejected for v1 because traces keep
every prompt, model output and code output unscrubbed (`core/trace.py` Span), and `RunBundle` is mostly
`dict[str, Any]` (`service.py`), so schema validation proves little. Regrade needs traces and result files
(`runner/regrade.py`). Start from `ArenaService.run_bundle(artifacts=True)` (`service.py`): decide which span fields
survive redaction, type the subset the step inspector reads, and set a size budget that still carries regrade's result
files.

**Effort:** M
**Priority:** P2
**Depends on:** shareable claims v1 shipped

### Evidence for self-declared self-hosted model names

**What:** Attach optional server-reported facts (quantization, context length, Ollama digest where listed) to
self-hosted roles in reproduction blocks, show them in the claim page's reproduction rows, and split the tally when they
differ.

**Why:** v1 claims identify Ollama, LM Studio and endpoint models by a "compare as" name that people type (re-review
D7). Two different quantizations can share a name, and their results then pool in one tally.

**Pros:** Mismatched serving becomes visible; self-hosted tallies get more trustworthy without a central name list.

**Cons:** Metadata differs per server type (Ollama, LM Studio, vLLM/LiteLLM), and much of it is optional or missing,
so the rules for "differ" need care.

**Context:** Re-review R19/R21 of `docs/designs/shareable-claims.md`. Until then names show as "self-declared" with the
caption "self-hosted: names are declared by people, serving may differ". Start from discovery: `llm/catalog.py`
`compatible_entries` already reads `max_model_len` / `context_length`; check what the Ollama and LM Studio listings in
`adapters/server/discovery.py` expose. Facts must stay optional fields of the closed repro schema and never include
endpoint names or URLs.

**Effort:** S-M
**Priority:** P3
**Depends on:** shareable claims v1 shipped

### Variant-only Beat-this runs

**What:** Offer a cheaper "variant only" Beat-this mode: run only the swapped setup and compare it with the claim's
published numbers, labeled "unpaired, conditions may differ", posted with `baseline: null` and never counted as a
reproduction.

**Why:** Every Beat-this run today also re-runs the claimed setup, so visitors pay twice to try one swap.

**Pros:** Roughly half the cost per swap; more people try swaps.

**Cons:** A weaker comparison (different day, provider state, keys) that people can misread; needs a new repro shape
and its own labels and tests.

**Context:** Raised in eng re-review 2 of `docs/designs/shareable-claims.md` (R23) after explaining why Beat this pairs
the claimed setup with the variant (same tasks and conditions, per-task paired test, free reproduction). Start from §4's
repro block (`variant` may already be null; this adds the mirror case) and §5 (must never enter the tally).

**Effort:** S
**Priority:** P3
**Depends on:** shareable claims v1 shipped

### Fewer GitHub requests and a size cap on Pages

**What:** Cut the GitHub requests a claim page and a post make, and cap GitHub response sizes in the browser. Post from
the run page with a head-only gist read (no re-download of the pinned claim), reuse the thread the claim page just
loaded, fetch comment pages in parallel, and keep the immutable pinned claim in memory per tab. On Pages, read
responses as text with a byte cap before parsing (the local proxy already caps at 2 MB).

**Why:** Without a token GitHub allows 60 requests an hour. A post costs up to 6 requests today and every claim view 2-4,
so active visitors hit the limit. A hostile thread of large comments is parsed in full on Pages.

**Context:** Performance and Codex findings in the /review of the shareable-claims branch (2026-10-10):
`web/src/lib/claims.ts` (`claim`, `thread`, `direct`), `web/src/components/ClaimBand.svelte` (`post`),
`src/llm_arena/adapters/server/gists.py` (one `AsyncClient` per request).

**Effort:** S
**Priority:** P2
**Depends on:** shareable claims v1 shipped

### Claim page polish from the design review

**What:** Close the design-checklist findings on the claim page:
- Show the variant's cost change and "(self-declared)" names in reproduction rows (design 7.3, 13.10, 13.11).
- Hide empty baseline fragments on rejected rows.
- Name the right provider in "Add a … key" from `keyRows()`, and build the partial-limit line from the run's priced
  providers.
- Give ClaimBand an h3 when it is embedded.
- Move focus back to whichever button asked for a token.
- Keep one persistent aria-live region for the posted state.
- Use unframed setup and Beat-this columns on phones (1.1).
- Give child controls 44 px touch targets.
- Drop the progress-bar width transition.
- Show "spent $X of $limit".
- Show unreachable endpoint catalogs even when no candidate was refused.

**Why:** v1 works end to end, but these differ from `docs/designs/shareable-claims.md` and some hurt screen-reader and
phone use.

**Context:** Design specialist findings in the /review of the shareable-claims branch (2026-10-10), mostly
`web/src/views/ClaimView.svelte` and `web/src/components/ClaimBand.svelte`. `/design-review` on the running site can do
them with screenshots.

**Effort:** M
**Priority:** P2
**Depends on:** shareable claims v1 shipped

### Smaller claim follow-ups

**What:**
- Keep imported run ids within the run-id limit (`importId` can append past 121 characters, and the re-import then
  fails).
- Turn pydantic and `ClaimError` messages from the Pages engine into one clean line, as the local app does, instead of
  the last traceback line.
- Share the claim size limits (256 KB, 300 comments, 65,536 characters, id patterns) as constants instead of repeating
  literals across `api.py`, `claims.py`, `gists.py` and `claims.ts`.
- Make `runner.fingerprint`'s digest and `SPEC_FIELDS` the only source for `claims.py`.

**Why:** Each one is small, but they drift or confuse: an export/import round trip breaks, Pages shows module paths, and
a changed limit gives 400s in only one layer.

**Context:** API-contract and maintainability findings in the /review of the shareable-claims branch (2026-10-10).

**Effort:** S
**Priority:** P3
**Depends on:** shareable claims v1 shipped

### Claims board slice 2: the measured role ranking

**What:** Add the measured-swap tier to the claims board's "Overall" tab (slice 1 ships it with appearance-based
entries only, design 5A): measured entries from one-role Beat-this swaps (all valid swaps, latest per user, claim,
role and entry, author swaps labeled) replace an entry's appearance number where swaps exist.

**Why:** The brainstorm asked for a role-wise model ranking (tool calling, code, writing, critique, decision). Slice 1
ships the board without it because its statistics aren't decided.

**Context:** `docs/designs/claims-board.md` section 6 and Open Question 2 (estimator: pooled paired deltas vs one
fitted scale per role group; the reference entry; pooling across scenarios). Swap pairs come from the stored `Repro`
objects' `per_task` (ledger copies), since `trust_stats` rows don't carry them. Spec-review notes R3-15 to R3-17
(decision-service policies vs LLM decision roles, author share for mixed entries, panel placement) apply here.

**Effort:** M
**Priority:** P2
**Depends on:** claims board slice 1 shipped; Open Question 2 decided

## Leaderboard

### Leaderboard and resume ignore the judge

**What:** Make the LLM judge part of how the local leaderboard groups trials and of the resume key, so runs graded by
different judges (or none) never share a row or reuse each other's trials.

**Why:** `setup_of`, `fingerprint` and `resume_key` (`runner/fingerprint.py:49-52`) leave out
`ExperimentConfig.judge`, and `RubricJudgeEvaluator` returns no scores without a judge, so one setup's pass rate
depends on the grader while its rows pool.

**Pros:** Leaderboard rows compare like with like; resuming after a judge change re-grades instead of reusing.

**Cons:** Existing judged runs regroup; needs care so unjudged runs keep their fingerprints (append the judge only when
set, as with endpoint fields) and a note for users whose rows split.

**Context:** Found in eng re-review 2 of `docs/designs/shareable-claims.md` (R24) while pinning the judge in claims
(R22). Affects `launch_brief`, `reflection_writing`, `chart_codegen` and `research_report`. Start from
`runner/fingerprint.py` and `report/leaderboard.py:4`; R6 of that plan promises existing fingerprints stay unchanged,
so this ships as its own change.

**Effort:** S-M
**Priority:** P2
**Depends on:** None

## Design

### Formalize the web UI's design system as DESIGN.md

**What:** Write DESIGN.md from the tokens, classes and formatters in `web/src/app.css` and `web/src/lib/format.ts`
(for example with `/design-consultation`).

**Why:** The app has a consistent but implicit design system. Every UI plan and design review currently re-derives
it from CSS, and small drifts creep in.

**Context:** The design review of `docs/designs/shareable-claims.md` (§12, "Design vocabulary (5.1)") already maps
page elements to tokens and classes: surfaces, text levels, `.pill`, `.note`, `.error`, `.card`,
`button.primary`, `p.lead`, `pct()` / `usd()` with tabular numerals, light and dark themes. Start from that table.
Afterwards, keep DESIGN.md in sync with app.css.

**Effort:** S
**Priority:** P3
**Depends on:** None

## Completed
