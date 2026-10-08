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
