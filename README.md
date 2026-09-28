# llm_arena

An evaluation arena for **local** (Ollama, LM Studio) and **remote** (OpenAI, Anthropic) language models. It covers classic
benchmarks and, above all, **agentic AI patterns**: reflection, tool use, code execution, ReAct, planning and
multi-agent workflows.

Every pipeline step is bound to a configurable model *role*. So "Qwen drafts, GPT critiques" and "a GPT planner with a
local executor" are one config line each. Each pipeline is scored **per step** (component evals read from the execution
trace) and **end to end** (final output and final state of a mocked environment). A static HTML report ranks the
configurations.

```
scenario × config (role → model bindings) × task × repeat  →  trace + scores  →  DuckDB  →  report.html
```

## Quick start

```bash
make install                      # uv sync --all-extras (Python 3.12); the CLI needs the `server` extra
cp .env.example .env              # OPENAI_API_KEY / ANTHROPIC_API_KEY for remote models; local servers need nothing
uv run arena models list          # discovered models (Ollama, LM Studio, OpenAI) with capabilities + prices
uv run arena models ping ollama:qwen3:14b openai:gpt-4.1-mini   # chat / tools / structured-output smoke test
uv run arena scenarios            # scenarios, their roles and parameters
uv run arena run configs/experiments/smoke.yaml            # runs + writes runs/<id>/report.html
make test                         # lint + mypy --strict + unit tests (no model server needed)
```

Other entry points:
- `arena run <cfg> --dry-run` prints the trial plan.
- `--run-id <id>` resumes a run: finished trials are skipped and failed ones retried.
- `--limit N` caps the tasks per scenario.
- `arena report <run-id> [--cdn] [--json]` rebuilds a report.
- `arena judge-calibrate` checks an LLM judge against hand labels.
- `arena mock-email` serves the mock mailbox over HTTP.
- `arena contracts [--check]` exports JSON Schemas, scenario data and conformance vectors for the web UI and other
  engines.
- `arena run … --docker` runs model-written code in Docker (`--network none`).
- `max_cost_usd` in an experiment stops the run at a spend limit.

## Local app

`make ui` (or `uv run arena ui`) starts the app on http://127.0.0.1:8787 (change it with `--port` or `ARENA_UI_PORT`
in `.env`). It provides:
- the discovered models
- scenarios with wiki links
- cost estimates
- runs with live progress (Server-Sent Events)
- reports

Details:
- **Keys** are read from `.env` on the server. You can also set a key for the current session in the app; it is held in
  server memory only. The API reports only whether a key is configured, never the key.
- **Access** is limited to 127.0.0.1 and localhost origins.
- **API:** the endpoints mirror `ArenaService`, and their JSON Schemas are in `contracts/schemas` (see `/docs` for the
  OpenAPI view):

  ```
  GET  /api/runtime   GET /api/scenarios   GET /api/models   PUT|DELETE /api/keys/{provider}
  POST /api/estimate  POST /api/runs       GET /api/runs     GET /api/runs/{id}/events (SSE)
  POST /api/runs/{id}/cancel               GET /api/runs/{id}/bundle   GET /api/runs/{id}/report
  ```

### Web UI

`make web` builds the Svelte UI (`web/`). It needs Node ≥ 20, and `arena ui` serves it. The UI has four views:
- **Models:** the catalog, filterable by capability, plus API keys.
- **Build:** pick scenarios, bind a model to each role (the choices are filtered by the role's capability needs, with
  prices), set parameters, estimate cost, start, or download the experiment as YAML.
- **Runs:** live progress, then an in-app report with heatmaps, confidence intervals, step metrics, arena ratings,
  traces and wiki links.
- **Overview:** the scenarios and benchmarks.

The UI uses only the `ArenaBackend` interface, and its TypeScript types are generated from `contracts/schemas`
(`npm run contracts`). The same UI will run the in-browser engine. `make test-web` runs svelte-check and vitest; for
development use `cd web && npm run dev`, which proxies `/api` to a running `arena ui`.

## Browser-only mode

The same UI also runs with no server at all, as on GitHub Pages. The arena's Python engine then runs in the tab via
Pyodide, in a Web Worker. Setup:
- Enter an OpenAI or Anthropic key in **Models**. It is kept in the tab's memory and sent only to the provider's API.
  Opting in keeps it in local storage on that device.
- Set a spend limit on each run.

What changes compared with the local app:
- **Models:** remote only (OpenAI, Anthropic), because a web page cannot reach your local model servers.
- **Code execution:** runs in a separate Pyodide worker that is terminated on timeout.
- **Benchmarks:** fetch their pinned files from the Hugging Face CDN.
- **Runs:** stored in the browser (IndexedDB). They can be exported and imported as run bundles, which the local app
  opens too.

`#/selftest` replays the conformance vectors inside the browser engine; all must pass.

To serve browser mode locally: `make web` (builds the engine wheel into `web/public/py`, then the UI), then open
`web/dist` with any static file server.

## What is in the arena

| Scenario | Pattern | Environment (all seeded / mocked) | Pass criteria |
|---|---|---|---|
| `reflection_sql` | reflection with execution feedback | SQLite of a fictional bike-rental company, with deliberate schema traps | final result set equals gold |
| `reflection_writing` | reflection (self or cross-model critic) | writing briefs with verifiable constraints | constraints met; judge rubric; arena |
| `chart_codegen` | code execution + vision critic | synthetic CSVs; figures introspected at `savefig` | chart renders and matches its spec |
| `email_assistant` | multi-step tool use | in-memory mailbox, frozen clock | final mailbox state, no collateral damage |
| `research_report` | tool use + reflection | BM25 corpus with sources in quality tiers and planted misinformation | fact recall, no misinformation, valid citations |
| `react_multihop` | ReAct (vs Act-only / CoT-only) | encyclopedia of a fictional world | exact match |
| `shop_codeact` | code as action | shop DB + Python API in a sandbox | final DB state + store policy |
| `support_desk` | control policies: who picks the next action, decides completion, gates risky actions | shop tools, oracle human approver, dev/test split | final state + store policy + customer informed; decision quality |
| `trip_planner` | plan-and-execute with replanning (vs a single loop) | flights, hotels, calendar; a flight sells out when booked | hard constraints checked by code |
| `launch_brief` | orchestrator + workers with typed handoffs (vs a single agent) | product catalog + trend reports | correct product, tagline, no misinformation |
| `gsm8k`, `mmlu_pro`, `ifeval`, `humaneval`, `mbpp` | classic benchmarks | public subsets at pinned revisions | per benchmark |
| `function_calling` | tool selection and arguments | own synthetic suite | AST-style call match |

Metrics, reports and ranking:
- Step metrics include tool-argument validity, redundant calls, forbidden actions, reviewer precision/recall,
  regressions caused by revision, plan repairs and replans, handoff acceptance, unsupported claims, and preferred-source
  ratio.
- Aggregates are pass rate with a bootstrap CI, pass^k, pass@k, a paired permutation test against the leader, tokens,
  cost, and p50/p95 latency.
- Open-ended scenarios also get pairwise judge battles, run with swapped positions and ranked with Bradley–Terry.

## Control policies

Most agents let the LLM make every control decision inside its loop. The arena can swap those decisions out and
score each one against ground truth. The decisions are: which tool next, is the task complete, must a human approve
this action, and does the finished run need review. A config chooses the decision maker:

```yaml
configs:
  - name: agent-decides                       # baseline
    roles: {"*": ollama:qwen3:14b}
  - name: cascade-controls
    roles: {"*": ollama:qwen3:14b, decider: ollama:qwen3:4b, escalation: ollama:qwen3:14b}
    decisions: {policy: cascade, control: policy, threshold: 0.8}   # llm | rules | cascade | jev
```

The report compares task success, cost and latency across configs, and adds per-decision accuracy, calibration
(Brier, log loss, bins), false-safe approvals and needless escalations. Tune thresholds on `split: dev`, report on
`split: test`. See `configs/experiments/decisions.yaml`. Jev (TypeSafe) needs `TYPESAFE_API_KEY` and works in the
local app and CLI; its API does not allow browser calls.

## Configuring models and experiments

**Models are discovered, not hard-coded.** `arena models list` queries the endpoints below and shows each model's
reference, parameters, quantization, context length, tool/vision/thinking support, whether it is loaded, and the price
per million tokens:

| Provider | Endpoint |
|---|---|
| Ollama | `/api/tags` + `/api/show` |
| LM Studio | `/api/v0/models` |
| OpenAI | `/v1/models` |

Use a reference directly in experiments: `ollama:qwen3:14b`, `lmstudio:qwen/qwen3-14b`, `openai:gpt-4.1-mini`.
- **Capabilities come from the server,** so role checks (e.g. a vision critic) work on any machine.
- **Models without native tool support** automatically use the JSON tool protocol.
- **A provider that isn't running** is reported and skipped.
- **Other flags:** `--needs vision` filters by capability; `--json` emits the catalog for tooling or a UI.

`configs/models.yaml` is optional and holds curated aliases for *call variants*: JSON tool mode, reasoning effort, a
pinned-temperature judge, the aisuite backend. An alias always wins over discovery. OpenAI prices live in
`configs/prices.yaml`. Unknown prices show as "unknown" rather than a guess.

```yaml
# configs/experiments/reflection.yaml (excerpt)
scenarios: [reflection_sql, reflection_writing]
repeats: 3                      # pass^k
judge: judge-gpt-4.1-mini       # pinned alias (temperature 0); its cost is reported separately
arena: {enabled: true}          # pairwise battles + Bradley–Terry ratings
configs:
  - name: no-reflection
    roles: {"*": ollama:qwen3:14b}          # "*" binds every role
    params: {reflection_rounds: 0}
  - name: local-gen+gpt-critic
    roles: {generator: ollama:qwen3:14b, writer: ollama:qwen3:14b, critic: openai:gpt-4.1-mini}
```

Role bindings are checked against each scenario's requirements before anything runs. For example, the chart critic
needs `vision`.

## Reusable LLM utilities

`llm_arena.llm` does not depend on the rest of the arena, so you can use it on its own:

```python
from llm_arena.adapters.server.clients import get_client   # server runtime; the browser uses ProtocolClient
from llm_arena.llm import parse_model_ref, structured, user

client = get_client(parse_model_ref("lmstudio:qwen/qwen3-14b"))
reply = await client.complete([user("Hello")])                       # LLMResponse: content, tool_calls, usage, reasoning
answer, _ = await structured(client, [user("…")], MyPydanticModel)   # json_schema + validate + repair
```

It handles:
- OpenAI, Anthropic, Ollama, LM Studio and vLLM through one interface: the official SDKs on the server (`backend:
  auto`), aisuite, or the transport-agnostic `ProtocolClient`, which also runs in the browser. All of them share pure
  request/response mappers.
- Native or JSON tool mode.
- Reasoning-model quirks: no temperature for GPT-5 and o-series models; `<think>` blocks and `reasoning_content` are
  split out.
- Retries, per-endpoint concurrency limits, cost accounting and an opt-in disk cache (`ARENA_CACHE_DIR`).
- A `ScriptedLLM` fake for tests.

## Documentation

- [docs/architecture.md](docs/architecture.md): engine, ports, adapters, contracts, and how to extend each.
- [docs/decisions/](docs/decisions/): architecture decision records (e.g. the Pyodide browser runtime).
- [docs/scenarios.md](docs/scenarios.md): every scenario, its step metrics and design rationale.
- [docs/metrics.md](docs/metrics.md): how scores, pass^k, CIs, significance tests and arena ratings are computed.
- [docs/PROVENANCE.md](docs/PROVENANCE.md): where ideas came from. No course material is copied.
- [docs/licenses.md](docs/licenses.md): licences of the benchmark datasets that are downloaded at runtime.
