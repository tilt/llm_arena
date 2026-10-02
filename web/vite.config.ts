import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// One id per build, in the bundle and in version.json: an open tab compares them to notice an upgrade.
const BUILD_ID = process.env.ARENA_BUILD_ID ?? Date.now().toString(36);
const CREDENTIAL_ORIGIN = process.env.VITE_CREDENTIAL_ORIGIN?.trim();
if (CREDENTIAL_ORIGIN) {
  const parsed = new URL(CREDENTIAL_ORIGIN);
  if (!(["http:", "https:"].includes(parsed.protocol)) || parsed.origin !== CREDENTIAL_ORIGIN) {
    throw new Error("VITE_CREDENTIAL_ORIGIN must be an exact http(s) origin without a path, query or fragment");
  }
}

// ARENA_BASE=/llm_arena/ for GitHub Pages; "/" when served by `arena ui`.
export default defineConfig({
  base: process.env.ARENA_BASE ?? "/",
  define: { __BUILD_ID__: JSON.stringify(BUILD_ID) },
  plugins: [svelte(), {
    name: "build-id",
    generateBundle() { this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ build: BUILD_ID }) }); },
  }],
  // Dev server proxies the API to a running `arena ui` (ARENA_UI_PORT, default 8787).
  server: { proxy: { "/api": `http://127.0.0.1:${process.env.ARENA_UI_PORT ?? "8787"}` } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
