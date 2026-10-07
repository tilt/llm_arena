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

## Requirements

Runs on **macOS and Linux** (on Windows, use WSL2). Tested on macOS and on a fresh Ubuntu 24.04.

| | Needed for | Install |
|---|---|---|
| `git`, `make` | everything | macOS: `xcode-select --install` · Linux: your package manager |
| [uv](https://docs.astral.sh/uv/) | everything; it installs Python 3.12 for the project | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js ≥ 20 | building the web UI (the CLI works without it) | macOS: `brew install node` · Linux: [nodejs.org](https://nodejs.org) or your package manager |
| Docker | isolating model-written code (recommended) | Docker Desktop · Linux: Docker Engine, and add yourself to the `docker` group |
| Ollama, LM Studio, Ollaya | local models (optional) | [ollama.com](https://ollama.com), [lmstudio.ai](https://lmstudio.ai) |
| API keys | remote models (optional) | `.env`: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY` |

## Quick start

```bash
git clone https://github.com/tilt/llm_arena.git && cd llm_arena
make setup                        # checks the requirements, installs the project, creates .env,
                                  # builds the web UI (with Node) and the sandbox image (with Docker)
make doctor                       # later: re-check tools and which local model servers are reachable
make ui                           # opens an authenticated link to the app on 127.0.0.1:8787
```

From the command line:

```bash
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
- `arena leaderboard [scenario]` ranks setups per scenario across all runs (also in the app's Leaderboard page).
- `arena regrade [run-id…] [--apply]` re-grades runs of an earlier scenario version whose prompts, tools and
  tasks are unchanged, so they join the current leaderboard (dry run by default; backs up before writing).
- `arena contracts [--check]` exports JSON Schemas, scenario data and conformance vectors for the web UI and other
  engines.
- `arena run … --sandbox auto|docker|unsafe-process` chooses where model-written code runs. `auto` (the default) uses
  Docker (`--network none`, no capabilities) when it runs and `make sandbox-image` was built. Without Docker, code
  scenarios are unavailable; `--sandbox unsafe-process` is the explicit compatibility mode and runs model code with
  your user account and network access. The old `subprocess` spelling remains as a deprecated alias. See
  [docs/security.md](docs/security.md).
- A resumed run (`--run-id`) refuses to continue if a finished trial's setup, task content or seed changed.
- `max_cost_usd` stops new calls using best-effort concurrent reservations. Set `budget_mode: strict` to reject calls
  whose price or maximum output cost cannot be bounded without changing the provider request.

## Local app

`make ui` (or `uv run arena ui`) starts the app on http://127.0.0.1:8787 (change it with `--port` or `ARENA_UI_PORT`
in `.env`) and opens a one-time token link that becomes an HttpOnly session cookie. Run `uv run arena ui --link` to
print that link again, or `uv run arena ui --new-token` to invalidate existing browser sessions. It provides:
- the discovered models, with capabilities and prices
- a page per scenario: what it tests, every task with its expected outcome, the workflow with a model per step
- model presets (a model per kind of step) and replacement studies
- cost estimates, runs with live progress (Server-Sent Events), reports, a step inspector and a cross-run leaderboard

Details:
- **Keys** are read from `.env` on the server. You can also set a key for the current session in the app; it is held in
  server memory only. The API reports only whether a key is configured, never the key.
- **Access** is limited to loopback Host headers and authenticated browser sessions. Cross-site mutations are rejected.
- **API:** the endpoints mirror `ArenaService`, and their JSON Schemas are in `contracts/schemas` (see `/docs` for the
  OpenAPI view):

  ```
  GET  /api/runtime   GET /api/scenarios   GET /api/scenarios/{id}/tasks   GET /api/models
  PUT|DELETE /api/keys/{provider}          GET /api/presets     PUT|DELETE /api/presets/{name}
  POST /api/estimate  POST /api/runs       GET /api/runs     GET /api/runs/{id}/events (SSE)
  POST /api/runs/{id}/cancel               GET /api/runs/{id}/bundle[?traces=&artifacts=]
  GET  /api/runs/{id}/report               GET /api/runs/{id}/trials/{trial}/trace
  GET  /api/runs/{id}/artifacts/{key}      GET /api/leaderboard
  PATCH /api/runs/{id}                     (rename a finished run and its setups; ids stay)
  ```

### Web UI

`make web` builds the Svelte UI (`web/`). It needs Node ≥ 20, and `arena ui` serves it. Its views:
- **Scenarios:** one page per scenario with tabs:
  - *Overview:* what it tests, the environment, pass criteria in plain words, traps, useful comparisons.
  - *Tasks:* every task with its prompt and expected outcome, searchable; run a single task.
  - *Workflow & models:* the workflow diagram; start from a preset, pick a model per step, set parameters and the
    control policy, estimate and run.
  - *Results:* this scenario's leaderboard; "Use this setup" loads an entry back.
- **Build:** either compare hand-built configurations across scenarios, or run a *replacement study* (baseline preset +
  candidate models + which steps to swap, with a live preview of the configurations).
- **Runs:** live progress, then the report: heatmaps, confidence intervals, step metrics, decision quality, the effect
  of each replaced step, arena ratings. Each trial opens the *step inspector*: the trial's workflow as a map, and for
  every step its input (new messages first), output, tool calls, code, decisions and files, such as the chart a
  vision critic saw. Deep links: `#/runs/<run>/trial/<trial>/step/<step>`.
- **Leaderboard:** every run pooled per scenario and setup, filterable by model.
- **Presets:** edit the model presets. The serverless version offers only presets whose models a web page can call
  (OpenAI, Anthropic).
- **Models:** the catalog, filterable by capability, plus API keys.

The UI uses only the `ArenaBackend` interface, and its TypeScript types are generated from `contracts/schemas`
(`npm run contracts`). The same UI will run the in-browser engine. `make test-web` runs svelte-check and vitest.

For Vite development, start the API with the exact development origin and without opening its own tab:

```bash
ARENA_DEV_ORIGIN=http://localhost:5173 uv run arena ui --no-open
cd web && npm run dev
```

In another terminal, run `uv run arena ui --link`, replace its `http://127.0.0.1:8787` origin with
`http://localhost:5173`, and open the resulting link once. Vite proxies the token exchange and subsequent `/api`
requests; the cookie remains HttpOnly. Do not configure `ARENA_DEV_ORIGIN` in production.

## Browser-only mode

The same UI also runs with no server at all, as on GitHub Pages. The arena's Python engine then runs in the tab via
Pyodide, in a Web Worker. Setup:
- Enter an OpenAI or Anthropic key in **Models**. It is kept in the tab's memory and sent only to the provider's API.
  The shared `tilt.github.io` Pages build is session-only. A deployment on a dedicated host may explicitly set
  `VITE_CREDENTIAL_ORIGIN` to its exact origin to offer a remember option, which stores the key unencrypted in local
  storage on that device. Every other origin removes the legacy `llm-arena.keys` entry without reading its contents.
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

## Model presets and replacement studies

A **model preset** gives every step a model by the kind of work it does: text, vision, code, agent or decision.
Two ship built in:
- **Local small:** Qwen3 4B with thinking off, Qwen3-VL 8B for images, and winnow via Ollaya for decisions.
- **OpenAI mini:** GPT-5 mini with low reasoning.

Edit them on the Presets page (saved to `configs/presets.local.yaml`), or add your own in `configs/presets.yaml`.
A config with `preset: local-small` binds every role you don't set explicitly (`baseline:` is still accepted).

A **replacement study** measures what one step's model is worth. It runs a preset as the baseline, then the same setup with
exactly one role swapped to each candidate. The report shows the change in pass rate on shared tasks, with a paired
test, plus the change in cost and latency:

```yaml
# configs/experiments/replacement-study.yaml
scenarios: [reflection_sql, chart_codegen]
limit: 3
study:
  baseline: local-small
  candidates: ["ollama:qwen3:14b#reasoning=none", "openai:gpt-5-mini#reasoning=low"]
  roles: [critic]            # default: every role except decision roles
```

Candidates replace only steps whose needs they meet: a text-only model never replaces a vision critic. Dedicated
decision models (`ollaya:winnow:e4b`, `jev:jev-latest`) can be candidates too; they replace control decisions.

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
A reference can carry call settings after `#`, for example `ollama:qwen3:4b#reasoning=none` (thinking off, about 10×
faster for Qwen3) or `openai:gpt-5-mini#reasoning=low,temperature=0`.
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
- [docs/principles.md](docs/principles.md): why we grade and rank the way we do: what a score measures, partial
  credit, reproducibility, fair comparison and uncertainty.
- [docs/scenarios.md](docs/scenarios.md): every scenario, its step metrics and design rationale.
- [docs/metrics.md](docs/metrics.md): how scores, pass^k, CIs, significance tests and arena ratings are computed.
- [docs/security.md](docs/security.md): threat model: sandboxing of model-written code, keys, spending, reports.
- [docs/related-work.md](docs/related-work.md): how the arena relates to Inspect AI, OpenAI Evals, τ-bench, BFCL and
  others, and when to use them instead.
- [docs/PROVENANCE.md](docs/PROVENANCE.md): where ideas came from. No course material is copied.
- [docs/licenses.md](docs/licenses.md): licences of the benchmark datasets that are downloaded at runtime.
