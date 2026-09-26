# Contributing

Thanks for helping improve the arena. Before you start, read [AGENTS.md](AGENTS.md). It covers the layout, the
change loop and the rules.

## Setup

```bash
make install            # Python 3.12 via uv, all extras
cd web && npm ci        # Node >= 20 for the web UI
pip install pre-commit && pre-commit install   # secret scanning on every commit
```

## Before opening a pull request

- Run `make test` (lint, strict types, architecture contracts, Python tests, contract freshness) and `make test-web`
  (svelte-check, vitest).
- If you changed scenarios, schemas or behaviour, run `make contracts` and `cd web && npm run contracts`, and commit
  the regenerated files. The diff shows exactly what other runtimes will see change.
- If you changed the browser engine, run `make web`, serve `web/dist` and check that `#/selftest` passes.

## Rules that matter here

- **Never commit keys.** Only `.env.example` belongs in the repo. CI runs gitleaks.
- **No course material.** Scenario ideas must be your own or general, reimplemented with fictional data. Record
  their origin in `docs/PROVENANCE.md`.
- **Tests never call real models.** Use `llm_arena.llm.testing.ScriptedLLM`.
- **Benchmark data is fetched at runtime** from pinned upstream revisions. Add each dataset's licence to
  `docs/licenses.md`.
