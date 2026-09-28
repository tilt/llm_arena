# Security and threat model

The arena runs untrusted model output, holds API keys that cost money, and renders results in a browser. This page
lists what it protects, how, and what remains your responsibility.

## What is at stake

| Asset | Threat |
|---|---|
| API keys (OpenAI, Anthropic, TypeSafe) | leaking into the public repo, logs, reports or the browser |
| Money | a web page or a runaway run spending on your keys |
| Your machine and files | model-written code (charts, CodeAct, HumanEval/MBPP) doing something harmful |
| The browser that opens a report or the app | model output or config names injected as script |

## Model output is untrusted

Everything a model writes is treated as data:

- **Code runs in a sandbox.** `--sandbox auto` (the default for `arena run` and `arena ui`) uses Docker when the
  daemon runs and the image `llm-arena-sandbox` exists (`make sandbox-image`). Containers get `--network none`,
  memory, CPU and process limits, `--cap-drop ALL` and `no-new-privileges`. Without Docker, code runs as a **local
  subprocess**: a temp directory, a clean environment, CPU and memory limits and a timeout. That protects against
  accidents, not against hostile code, because the process has your user's permissions and network access. The CLI
  and the app say so prominently. Use `--sandbox docker` to refuse to run without isolation.
- **Browser mode** runs code in a separate Pyodide worker, which is terminated on timeout. It is confined by the
  browser, but it shares the tab's network access.
- **Artifacts** (images, JSON, generated files) are served with `X-Content-Type-Options: nosniff` and a
  `Content-Security-Policy: default-src 'none'; sandbox` header. Keys are validated and resolved strictly inside the
  run folder, so `../` paths are rejected.
- **Static HTML reports** embed their data with JSON escaped for `<script>` (`<`, `>`, `&`, U+2028/U+2029), so a
  config or model name like `</script><script>…` stays text. A `Content-Security-Policy` meta tag allows only the
  report's own inline script and styles (plus the pinned Plotly CDN when it is not inlined). Everything else in
  the page is autoescaped by Jinja.
- **The web app** renders all model output as text (Svelte escapes by default; no `{@html}`).

## Keys and spending

- **Keys live in `.env` (git-ignored) or in memory.** The repo contains only `.env.example`. CI and the pre-commit
  hook run gitleaks on every commit.
- **The local app never returns key material.** Its API reports only whether a key is set and where from (`env`,
  `session`, `missing`). A key set in the app is held in server memory for the session.
- **The local app binds to 127.0.0.1,** and CORS allows only its own origin and the Vite dev server. Any process on
  your machine can still call it, and so spend your keys, just as it could read `.env`. The CLI has no option to
  bind elsewhere; do not forward or tunnel the port.
- **Spend limits.** `max_cost_usd` stops a run once model spend reaches the limit. The UI sets one by default. Use
  project keys with a hard limit at the provider.
- **Browser mode keeps keys in the tab's memory.** They are sent only to the provider's API and are written to local
  storage only if you opt in. TypeSafe's Jev is not called from the browser: its API does not allow cross-origin
  requests.
- **Ollaya and Ollama run on your machine;** calls to them do not leave it.

## Residual risks

- **Subprocess mode is not a security boundary.** Prefer Docker for untrusted code, and always for code from models
  you do not control.
- **Prompt injection.** Scenario content is synthetic and fixed. Live search (`--live`, Tavily or arXiv) brings in
  web content that could steer an agent. Results can be wrong; the tools cannot do more than their mock
  environments allow.
- **Supply chain.** Dependencies are pinned in `uv.lock` and `web/package-lock.json`. The browser loads Pyodide
  from a pinned jsDelivr URL.
