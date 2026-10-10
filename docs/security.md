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
- **OpenAI-compatible endpoints** (named servers such as vLLM; `configs/endpoints.local.yaml` or the Models page):
  - A key is bound to one endpoint and sent only to it, never to another host.
    - An env key applies only through the `api_key_env` written next to the URL in the YAML file. No variable is read
      just because its name matches an endpoint's name, and the provider-wide `ARENA_OPENAI_COMPATIBLE_KEY` is never
      used for a named endpoint.
    - The app cannot set `api_key_env`, so a page cannot point an existing key (say `OPENAI_API_KEY`) at a host.
    - Changing an endpoint's URL in the app forgets its session key and removes its `api_key_env` from the file, so
      the env key stays behind even after a restart.
    - Session keys live in the key store's memory, not in the process environment. A model resolved before a move
      gets no session key (`llm/registry.py:bound_session_key`).
    - A run that is already going keeps the clients it built: they still send the old key to the old URL until the
      run ends. Editing or removing an endpoint never sends a key to a new host, but it does not stop calls already
      underway either; cancel the run for that.
  - Keys travel only over https, or over plain http to a loopback or private-network address. The engine refuses a
    key for a public `http://` URL (`llm/spec.py:key_transport_ok`). URLs with credentials, a query or a fragment
    are rejected.
  - Endpoint URLs are not persisted with runs: experiments store references (`gpu-box:model`), and model errors
    name the endpoint instead of its URL (`ModelSpec.redact`).
  - The setup records the endpoint's identity instead: an HMAC of its URL under a random per-endpoint salt
    (`Endpoint.identity`). A moved endpoint therefore never pools or resumes with earlier runs, and a run bundle does
    not reveal the URL. A plain hash would: an IP address and port can be brute-forced from one in seconds.
  - Endpoints are defined only by you, in the YAML file or the form. A shared link, preset or run bundle cannot
    define one, so it cannot redirect a key.
  - Browser mode stores endpoint definitions under the same rule as keys: only on the exact `VITE_CREDENTIAL_ORIGIN`,
    and only when you choose to remember them. On any other origin, including the shared `tilt.github.io`, they
    stay in the tab's memory, and a stored `llm-arena.endpoints` entry is deleted unread.
  - The local app calls whatever endpoint URL its authenticated user enters, including LAN addresses; that is the
    point of the feature, and the session cookie and origin checks keep other sites from adding one.
- **Ollaya and Ollama run on your machine;** calls to them do not leave it.
- **Shared claims are untrusted input** (`llm_arena/claims.py`). A claim or reproduction is checked against closed
  schemas: unknown fields, endpoint fields, `base_url`, providers other than OpenAI, Anthropic or a declared
  self-hosted name, params outside a scenario's choices, live-only params and benchmark scenarios are all refused
  before anything runs. Pages renders a narrow, type-checked preview as plain text until the engine has validated the
  claim. Claims carry setups and results only: no prompts, traces or endpoint names, identities or URLs.
- **GitHub tokens** (posting claims and reproductions as gists):
  - Pages keeps a pasted token in the tab's memory only and sends it only to `api.github.com`. GitHub reads go out
    without a token unless one is set, and never through the HTTP cache.
  - The local app reads `GITHUB_TOKEN` through its key store (the `github` entry, shown as "GitHub (claims)"), and
    `adapters/server/gists.py` calls only the fixed GitHub API base. It checks gist ids, revisions, pages and comment
    ids before building a URL, follows no redirects, caps responses at 2 MB and comments at 65,536 characters, and
    times out after 10 s. The page stays on `connect-src 'self'`.
  - The local app posts only a reproduction block exactly as the engine writes it, and creates only public gists with
    a `claim.json` that validates, so the token can't be used for anything else through the app.
  - The token can read, edit and delete all your gists; both front ends say so where it is entered.

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
