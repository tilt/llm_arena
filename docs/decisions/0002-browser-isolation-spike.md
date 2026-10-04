# 0002: Opaque-origin browser sandbox spike

- **Status:** accepted for Chromium, Firefox and WebKit, 2026-10-03
- **Scope:** test-only proof that gates the stronger browser sandbox boundary. It does not itself change production
  execution or claim that the current browser worker is network-isolated.

## Harness

`web/tests/browser` runs on macOS with Playwright 1.63.0 against its pinned Chrome for Testing 153.0.8010.12,
Firefox 155.0 and WebKit 26.6 builds. A loopback-only Node listener serves inert fixtures and records every canary
request or WebSocket upgrade. No probe names or contacts a public host.

The parent fetches the bootstrap, runtime fixture and package fixture as bytes and verifies their checked-in SHA-256
digests. Only after all three match does it create a `sandbox="allow-scripts"` iframe. The iframe loads the bootstrap
as an external script with matching SRI and CSP SHA-256 declarations; its policy has no `unsafe-inline`, permits only
the exact script hash plus `wasm-unsafe-eval`, allows blob workers, and sets `connect-src 'none'`.

The first attempted design created a verified bootstrap blob in the parent and passed its URL to the opaque iframe.
All three engines refused to run it. Parent-created blob URLs are therefore **not** a supported bootstrap mechanism.

## Results

| Assertion | Chromium | Firefox | WebKit |
|---|---:|---:|---:|
| iframe message origin is opaque (`null`) | pass | pass | pass |
| iframe cannot use local or session storage | pass | pass | pass |
| iframe `fetch`, WebSocket and EventSource reach no loopback listener | pass | pass | pass |
| iframe dynamic remote import reaches no loopback listener | pass | pass | pass |
| blob-worker `fetch`, WebSocket, EventSource, `importScripts` and dynamic import reach no listener | pass | pass | pass |
| blob worker cannot use local or session storage | pass | pass | pass |
| runtime and package bytes arrive with the verified SHA-256 values | pass | pass | pass |
| external SRI + identical CSP hash runs without inline script permission | pass | pass | pass |
| strict source/origin/request-id/schema checks reject a malformed message | pass | pass | pass |

Playwright may surface a browser-level EventSource request event even though CSP prevents a network hit; the
loopback listener is the authoritative traffic assertion and remained empty in every engine. The harness also
requires a `connect-src` CSP violation event.

## Decision

Phase 4 may use the external SRI plus CSP-hash bootstrap and strict opaque-origin messaging in these three engine
families. It may not use a parent-created bootstrap blob. Production performs a same-origin canary self-check at
sandbox start and requires both an opaque origin and a blocked request before returning `isolated`. The current
production worker is disposable and uses pre-execution asset verification plus network API locking, but it is not
yet hosted by that iframe and therefore remains truthfully labelled `not network-isolated`.

Run locally with:

```bash
cd web
npx playwright install chromium firefox webkit
npm run test:isolation
```
