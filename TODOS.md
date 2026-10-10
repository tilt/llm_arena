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
