import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// ARENA_BASE=/llm_arena/ for GitHub Pages; "/" when served by `arena ui`.
export default defineConfig({
  base: process.env.ARENA_BASE ?? "/",
  plugins: [svelte()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
