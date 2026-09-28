import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// ARENA_BASE=/llm_arena/ for GitHub Pages; "/" when served by `arena ui`.
export default defineConfig({
  base: process.env.ARENA_BASE ?? "/",
  plugins: [svelte()],
  // Dev server proxies the API to a running `arena ui` (ARENA_UI_PORT, default 8787).
  server: { proxy: { "/api": `http://127.0.0.1:${process.env.ARENA_UI_PORT ?? "8787"}` } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
