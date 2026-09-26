# AGENTS.md

This is the working agreement for humans and agents changing this repository.

`llm_arena` evaluates language models on benchmarks and agentic-pattern pipelines. A score is only worth something if it
is **reproducible** and **attributable**:
- Mocked environments are seeded.
- Every model call is traced to a role.
- Every trial persists its trace.

A change that makes scores depend on hidden state (wall clock, network, shared mutable fixtures) is a bug, even when
the tests pass.

## Layout and dependency direction

| Path | What lives there |
|---|---|
| `src/llm_arena/llm` | Pure LLM layer: spec, protocol mappers, transport port, `ProtocolClient`, catalog builders. Imports nothing else from llm_arena. |
| `src/llm_arena/core` | Trace/Span, Task, errors. |
| `src/llm_arena/tools`, `mocks`, `sandbox`, `patterns` | Tool registry, seeded environments, sandbox port, agentic patterns. |
| `src/llm_arena/scenarios`, `benchmarks` | Tasks + pipeline + evaluators + manifest + fixtures; registered via `@register`. |
| `src/llm_arena/eval`, `report/aggregate.py` | Scores, metrics, judge, calibration; pure run summaries. |
| `src/llm_arena/runner`, `service.py` | Orchestration behind ports (`RunStore`, `Runtime`, events, budget) and the `ArenaService` facade. |
| `src/llm_arena/conformance.py`, `contracts.py` | Conformance cases and the contract exporter (`contracts/`). |
| `src/llm_arena/adapters/server` | SDK clients, httpx, discovery, subprocess/Docker sandbox, DuckDB, Hub datasets, HTML report, CLI progress. |
| `src/llm_arena/adapters/browser` | Pyodide fetch transport. |
| `src/llm_arena/server` | Local app: FastAPI over ArenaService, SSE event channels, session key store. |
| `src/llm_arena/cli.py` | Typer CLI composing the server runtime (`arena run`, `arena ui`, …). |
| `contracts/` | Generated JSON Schemas, scenario data, conformance vectors. Regenerate with `make contracts`. |

Everything outside `adapters/` and `cli.py` is the **engine**, and it must stay pure. `import-linter` enforces this:
no SDK, network, storage, process or UI libraries, so the engine keeps loading in Pyodide.

## The loop for every change

1. `make format`
2. `make validate`, which runs ruff, the format check, `mypy --strict` and the import-linter contracts. It must be
   green.
3. `make test`, which includes the contracts freshness check (`make contracts` regenerates the contracts; review the
   diff). Unit tests use `ScriptedLLM` and mocks only. **No test may need a model server or API key.** Live
   checks go behind `@pytest.mark.live`.

## Rules

- **Copyright.** Never copy code, prompts, prose, data or examples from `../course_agentic_ai` (deeplearning.ai
  material). Reimplement ideas from general descriptions and from our own wiki. Use new, fictional domains.
  `tests/test_provenance.py` fails on long verbatim overlaps. Record the origin of new scenario ideas in
  `docs/PROVENANCE.md`.
- **Benchmarks** are downloaded at runtime at a pinned revision and never vendored. Add each one's licence to
  `docs/licenses.md`.
- **Scenarios:**
  - Grade with code wherever ground truth is objective (state diffs, result sets, constraints). Use the LLM judge only
    for what code cannot check, and never as the only pass criterion.
  - Every scenario ships a test with a scripted good agent (passes) and a scripted bad agent (fails the intended
    check).
- **Pass criteria** combine safety and quality: for example state correct **and** no collateral damage.
- **Types and style:**
  - `from __future__ import annotations` at the top of every module.
  - Frozen dataclasses or pydantic models for data.
  - Comments explain *why*.
  - One responsibility per module.
- **Config** comes from YAML plus `ARENA_*` env vars, read in `llm/registry.py` and `runner/config.py` only.
