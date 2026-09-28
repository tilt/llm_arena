# Architecture

One Python engine drives three front ends: the CLI, the local app (`llm_arena.server`, FastAPI + SSE), and the browser
(`adapters/browser` in a Pyodide Web Worker, e.g. on GitHub Pages). The engine is pure. Everything environment-specific enters through **ports** and is implemented by
**adapters**. What other runtimes consume is exported as **contracts**.

```
   CLI (typer)        local app (FastAPI + SPA)        browser (SPA + Pyodide worker)
        │                     │                                  │
        └─────────────► ArenaService (llm_arena/service.py) ◄────┘   JSON in / JSON out + RunEvents
                               │
   engine (pure): runner · scenarios · patterns · eval · report.aggregate · llm (mappers) · mocks · tools
                               │ ports
   ┌───────────────────────────┴───────────────────────────────────────────────┐
   │ Runtime: client_factory · discover · sandbox · live_search   RunStore   ChatTransport │
   └───────────────────────────┬───────────────────────────────────────────────┘
   adapters/server: openai & anthropic SDK clients, httpx transport, discovery, subprocess/Docker sandbox,
                    DuckDB store, Hub datasets, HTML report, live search, rich progress
   adapters/browser: BrowserArena (worker entry), pyfetch transport + discovery, JS-bridged sandbox worker,
                     prefetched Hugging Face datasets (DuckDB in Pyodide for parquet)
```

`import-linter` enforces the boundary (`make validate`):
- The engine never imports adapters, the CLI, or any SDK, network, storage or process library.
- `llm_arena.llm` is independent of the rest of the arena.
- Browser adapters never import server adapters.

The base install (pydantic + pyyaml) is exactly what the engine needs, and it loads in Pyodide (see
`docs/decisions/0001-browser-runtime.md`).

## Key abstractions

| Abstraction | Where | Role |
|---|---|---|
| `ModelSpec` | `llm/spec.py` | One model: provider (`openai`, `anthropic`, `ollama`, `lmstudio`, `openai_compatible`), backend, tool mode, sampling, capabilities, prices. |
| Protocol mappers | `llm/protocols/{openai_chat,anthropic_messages}.py` | Pure request/response mapping on JSON dicts. Shared by every client in every runtime. |
| `ChatTransport` + `ProtocolClient` | `llm/transport.py`, `llm/http_client.py` | POST JSON → JSON. `ProtocolClient` adds retries (quota errors are permanent), JSON tool mode and caching on top of any transport. |
| SDK clients | `adapters/server/{openai_sdk,anthropic_sdk,aisuite_client}.py` | Official SDKs on the server (`backend: auto`); they reuse the same mappers. |
| `Catalog` | `llm/catalog.py` (pure builders), `adapters/server/discovery.py` (HTTP) | Installed and available models with capabilities and prices. |
| `Runtime` | `runner/ports.py` | What a run needs from its environment: client factory, discovery, sandbox, live search. |
| `RunStore` | `runner/ports.py`; `runner/memory_store.py`, `adapters/server/duckdb_store.py` | Trials, scores, battles, traces. Every store returns the same rows (`RunData`). |
| `RunEvent` | `runner/events.py` | Progress events. The CLI draws a progress bar, the app streams SSE, the worker posts messages. |
| `BudgetGuard` | `runner/budget.py` | `max_cost_usd`: charges every call and stops the run at the limit. |
| `Scenario` + manifest | `scenarios/base.py`, `scenarios/manifest.py` | Tasks, pipeline, evaluators, roles with capability needs, params with choices, requirements, and wiki links. |
| API models | `api.py` | Request/response models of the app API (StartRun, RunListing, RuntimeResponse, SetKey), exported as schemas. |
| Local app | `server/{app,channels,keys}.py` | FastAPI over ArenaService; per-run event channels with replay; session key store that never returns keys. |
| `ArenaService` | `service.py` | `list_scenarios`, `catalog`, `runtime_info`, `estimate`, `start_run`/`wait`/`cancel`, `run_bundle`. |
| `Trace` / `Span` | `core/trace.py` | Nested spans. Step evaluators read them. |
| `DecisionPolicy` | `decisions/` | Typed control questions (noul / choice / score) answered by LLM, rule, cascade or Jev policies. `TracedPolicy` records a `decision` span with ground-truth labels; `records.py` turns them into rows and quality metrics. Jev enters as `Runtime.jev` (server only). |

## Browser runtime (web/src/engine)

- `engine.worker.ts` loads Pyodide from jsDelivr (pinned), installs the arena wheel served with the site
  (`web/public/py`, built by `make web-engine`), and calls `adapters/browser/bootstrap.create_arena`. `WorkerBackend`
  (`web/src/lib/worker-backend.ts`) implements the same `ArenaBackend` interface as the HTTP client.
- `sandbox.worker.ts` is a second Pyodide with matplotlib and pandas. The engine terminates and replaces it on
  timeout.
- Finished runs are saved as `RunBundle`s in IndexedDB. Keys stay in worker memory unless the user opts in to
  local storage.
- `#/selftest` replays `contracts/conformance` in the browser engine. All 13 cases pass, including the control-policy cases (decision record 0001).

## Contracts (`contracts/`, generated by `arena contracts`)

| Path | Contents | Consumer |
|---|---|---|
| `schemas/*.schema.json` | JSON Schemas: ModelSpec, CatalogEntry, ScenarioManifest, ExperimentConfig, RunEvent, Task, Score, Trace, RunBundle, RuntimeInfo, Estimate | web UI (generated TypeScript types), any other engine |
| `scenarios/<id>/` | manifest, tasks, fixtures (seeded DB dump, mailbox, corpora, shop/travel data, CSVs, tool schemas, rubrics, handoff schemas) | another engine; documentation |
| `conformance/*.json` | Scripted cases: the exact requests each role received (prompts included) and all expected scores | Pyodide build and any TypeScript port must reproduce them |

`tests/test_contracts.py` fails if the checked-in contracts drift from the engine. The Python engine stays the single
source of truth.

## Design decisions

- **Mocked by default, live optional.** Deterministic environments make scores comparable across models and runs.
- **State-based grading.** Agents are graded on the final environment state. Collateral damage is its own pass
  criterion.
- **Code evaluators first, judge second.** The judge is pinned, reported separately, calibratable, and
  position-swapped in pairwise battles.
- **One mapping, many transports.** The server SDKs and the browser's fetch send identical requests.
- **Serialized local trials.** A trial reserves every model endpoint it uses before its clock starts, so local servers
  (concurrency 1) run trials sequentially and latencies stay honest.
- **Sandbox as a port.** Subprocess or Docker on the server; a terminable Pyodide worker in the browser. Scenarios
  that need one declare `requires: sandbox`.

## Extending

- **New scenario:**
  - Subclass `Scenario` and set `title`, `requires`, `param_choices`, `tokens_per_trial` and `fixtures()`.
  - Bump its `version` whenever prompts, tools or evaluators change, so the leaderboard does not pool old and new
    results.
  - Register it and add it to `scenarios/catalog.py`.
  - Add good/bad scripted tests, plus a conformance case in `conformance.py`.
  - Run `arena contracts`.
- **New provider:** write a pure mapper in `llm/protocols/`, dispatch it in `llm/http_client.protocol_for`, and
  optionally add an SDK adapter, a discovery probe and prices.
- **New runtime:** provide a `Runtime` and a `RunStore`, then call `ArenaService`.
