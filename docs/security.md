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
  a read-only root filesystem, memory, CPU, output and process limits, `--cap-drop ALL` and `no-new-privileges`.
  Without a usable sandbox image, `auto` leaves code scenarios unavailable. `--sandbox unsafe-process` is the
  explicit compatibility mode: it uses a temporary work directory and resource limits, but model code still has
  your user's permissions and network access. The CLI and app label it as unsafe.
- **Browser mode** gives every code execution a fresh Pyodide worker and terminates it after success, failure,
  timeout or cancellation. At most two execute concurrently, with one pre-warmed spare. Runtime and package bytes
  are fetched as inert data and checked against the repository's SHA-256 manifest before any module, WebAssembly or
  wheel is loaded. The worker then locks its direct network APIs. The production worker is not yet hosted in the
  proven opaque-origin CSP iframe, so the runtime canary deliberately reports **browser sandbox: not
  network-isolated**. Disposable workers and API locking reduce risk but are not described as a browser-enforced
  security boundary.
- **Artifacts** (images, JSON, generated files) are served with `X-Content-Type-Options: nosniff` and a
  `Content-Security-Policy: default-src 'none'; sandbox` header. Keys are validated and resolved strictly inside the
  run folder, so `../` paths are rejected.
- **Static HTML reports** embed their data with JSON escaped for `<script>` (`<`, `>`, `&`, U+2028/U+2029), so a
  config or model name like `</script><script>…` stays text. Each report gets a fresh CSP nonce for its two required
  scripts; served reports carry the same policy in the HTTP header, while standalone reports carry it in a meta tag.
  Everything else in the page is autoescaped by Jinja.
- **The web app** renders all model output as text (Svelte escapes by default; no `{@html}`).

## Keys and spending

- **Keys live in `.env` (git-ignored) or in memory.** The repo contains only `.env.example`. CI and the pre-commit
  hook run gitleaks on every commit.
- **The local app never returns key material.** Its API reports only whether a key is set and where from (`env`,
  `session`, `missing`). A key set in the app is held in server memory for the session.
- **The local app binds to 127.0.0.1 and requires a session cookie.** `arena ui` creates a private 256-bit token in
  `$XDG_CONFIG_HOME/llm-arena/ui-token` (normally `~/.config/llm-arena/ui-token`), opens it in a URL fragment, removes
  the fragment immediately, and exchanges it for a derived HttpOnly, host-only, SameSite cookie. The raw token is not
  placed in the cookie. `arena ui --link` prints the link and `--new-token` rotates it, invalidating old cookies.
  Host validation rejects DNS-rebinding names, and mutation requests require the exact server origin or the one
  explicitly configured `ARENA_DEV_ORIGIN`. The CLI has no option to bind elsewhere; do not forward or tunnel the
  port. A process running as your user can still read the token or `.env`; this boundary protects against websites
  and other OS users, not a process already acting as you.
- **Spend limits.** `max_cost_usd` uses concurrent call reservations and stops admitting calls near the limit. Calls
  already running can finish, so the default mode is explicitly best effort. Set `budget_mode: strict` to refuse
  unknown prices and requests without a finite cost bound. The UI sets a best-effort limit by default. Use
  project keys with a hard limit at the provider.
- **Browser mode keeps keys in the tab's memory by default.** They are sent only to the provider's API. Persistent
  keys are available only when the production build names an exact `VITE_CREDENTIAL_ORIGIN` and the page's origin
  matches it exactly. The opt-in stores keys unencrypted in local storage. Every other origin hides the option and
  deletes the legacy `llm-arena.keys` entry without parsing or sending it to the engine. TypeSafe's Jev is not called
  from the browser: its API does not allow cross-origin requests. The current `tilt.github.io/llm_arena/` deployment
  shares an origin with other project sites, so it intentionally does not enable persistent keys.
- **Ollaya and Ollama run on your machine;** calls to them do not leave it.

## Residual risks

- **Subprocess mode is not a security boundary.** Prefer Docker for untrusted code, and always for code from models
  you do not control. It is available only through the explicit `unsafe-process` option (the deprecated `subprocess`
  spelling is an alias).
- **Prompt injection.** Scenario content is synthetic and fixed. Live search (`--live`, Tavily or arXiv) brings in
  web content that could steer an agent. Results can be wrong; the tools cannot do more than their mock
  environments allow.
- **Supply chain.** Dependencies are pinned in `uv.lock` and `web/package-lock.json`. Browser Pyodide core and
  pandas/matplotlib dependency artifacts are pinned in `web/src/engine/pyodide-assets.ts`; the build checks core
  bytes against the exact npm package and wheel digests against Pyodide's lockfile. Runtime code is imported only
  after SHA-256 verification.
