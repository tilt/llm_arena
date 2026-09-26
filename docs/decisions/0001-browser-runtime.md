# 0001: Browser runtime is Pyodide (go)

- **Status:** accepted, 2026-09-26
- **Context:** the arena should run on GitHub Pages without a server, using the visitor's own API key. We either run the
  existing Python engine in the browser (Pyodide) or port it to TypeScript.
- **Decision:** run the Python engine in Pyodide inside Web Workers. The TypeScript port stays a fallback. The rules
  that keep that fallback cheap stay in force regardless: content as data, JSON-Schema contracts, conformance vectors.

## Evidence (spike in `spikes/pyodide/`)

| Check | Result |
|---|---|
| Module imports in Pyodide 314.0.7 (Node) | 65/73. Only `resource` (the subprocess sandbox; now imported lazily) and `fastapi` (the server) failed. |
| Scenarios in Pyodide (Node) | `reflection_sql` (sqlite3 from the stdlib), `email_assistant` and `react_multihop` pass with scripted models. |
| Live model call via `pyodide.http.pyfetch` | Reached OpenAI through the existing request mapping and `parse_completion`. It returned HTTP 429 only because the test account had no credit. |
| Real browser (headless Chrome, fresh profile) | The engine worker cold-starts in **5.5 s** (Pyodide from jsDelivr + wheel). Two scenarios pass in 0.6 s. |
| Sandbox worker | Starts in 1.0 s. The matplotlib chart renders and is introspected. An infinite loop is killed after the 3 s timeout, and a replacement worker is ready in 1.0 s. |
| CORS from `https://tilt.github.io` | OpenAI echoes the origin and allows `authorization`. Anthropic allows `*` with `anthropic-dangerous-direct-browser-access`. The Hugging Face CDN allows the origin. |

## Consequences

- **Engine vs sandbox.** Model-written code never runs in the engine's interpreter. It runs in a separate sandbox worker
  that is terminated on timeout, which is the browser equivalent of the subprocess sandbox.
- **Lean core.** Installing the current wheel makes Pyodide pull in duckdb, openai, pandas, rich and matplotlib. The
  lean-core split (phase 1) must drop these from the engine's imports to cut the cold start.
- **Transport-agnostic LLM layer.** The spike's `FetchChatClient` reused the existing pure mapping functions. Phase 1
  formalizes this as `ChatTransport` (httpx on the server, pyfetch in the browser).
- **Package data.** Scenario data paths must not assume a source checkout (`DATA_DIR` in `scenarios/base.py`). Package
  data is resolved via `importlib.resources`.

## Reproduce

```bash
uv build --wheel -o spikes/pyodide/dist
cd spikes/pyodide && npm install pyodide@314.0.7
node probe_imports.mjs dist/llm_arena-0.1.0-py3-none-any.whl       # imports
node run_scenarios.mjs dist/llm_arena-0.1.0-py3-none-any.whl       # scenarios (+ live call if OPENAI_API_KEY is set)
python3 -m http.server 8765 --bind 127.0.0.1 &                      # from spikes/pyodide
node cdp_run.mjs http://127.0.0.1:8765/browser/index.html           # real browser workers
```
