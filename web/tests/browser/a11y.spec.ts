// Color contrast on the built site (browser mode, the real Pyodide engine): the main routes in the light and the dark
// theme, with zero axe color-contrast violations. The token math is in src/lib/contrast.test.ts; this scan checks what
// the pages render. GitHub and board.json are mocked. Run `make web` first.
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const SITE = "http://127.0.0.1:4175/";
const GIST = "a".repeat(32);
const REV = "b".repeat(40);
const vector = JSON.parse(readFileSync(new URL("../../../contracts/conformance/claim-mixed-thread.json", import.meta.url), "utf8")) as {
  input: { claim: string };
};

const row = (hash: string, people: number, model: string, rate: number, low: number) => ({
  gist_id: GIST, revision: REV, claim_hash: hash.repeat(64), owner: "alice", scenario: "email_assistant",
  scenario_version: "2", state: "ok", runnable: true, roles: { agent: { provider: "openai", model, backend: "auto",
    tool_mode: "native", temperature: 0.2, reasoning_effort: null, max_tokens: 1024 } },
  decisions: null, judge: null, tier: people >= 3 ? "verified" : people ? "reproduced" : "claimed", people,
  reproducers: Array.from({ length: people }, (_, i) => `user${i}`), rate, low, high: Math.min(1, rate + 0.06), tasks: 11,
  step_credit: 0.9, criteria: { state_correct: { passed: 20, graded: 22 }, answer_correct: { passed: 18, graded: 22 } },
  cost_usd_per_task: 0.004, cost_source: people ? "reproduced" : "claimed", claimed_rate: rate, reproduce_usd: 0.05,
  made_at: "2026-10-11T10:00:00+00:00", refreshed_at: "2026-10-12T06:17:00+00:00", notes: [],
});

// One row per tier, so every tier pill and both feeds' pills are on the page.
const BOARD = {
  board_version: 1, built_at: new Date().toISOString(), claims: 3, reproductions: 5,
  scenarios: [{
    scenario: "email_assistant", version: "2",
    ranked: [row("1", 4, "gpt-4.1", 0.92, 0.84), row("2", 1, "gpt-4.1-mini", 0.86, 0.79)],
    unreproduced: [row("3", 0, "claude-sonnet-4.5", 1.0, 0.74)],
    merged: ["1".repeat(64), "2".repeat(64), "3".repeat(64)], older: [],
  }],
  overall: {
    reproduced: { all: [{ provider: "openai", model: "gpt-4.1", reasoning_effort: null, tool_mode: "native", score: 0, raw: 0.92,
      setups: 1, scenarios: 1, only_claim: 0, claims: ["1".repeat(64)] }] },
    merged: {},
  },
  delisted: [], ledger_lines: 5, ledger_head: "0".repeat(64), registry_entries: 3, registry_head: "0".repeat(64),
};

async function mockData(page: Page): Promise<void> {
  await page.route("**/board.json", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(BOARD) }));
  await page.context().route("https://api.github.com/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type, accept" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body),
      headers: cors });
    if (path === `/gists/${GIST}/${REV}`) return json({ files: { "claim.json": { content: vector.input.claim } }, owner: { login: "alice" } });
    if (path === `/gists/${GIST}`) return json({ history: [{ version: REV }], comments: 0, html_url: "https://gist.github.com/x" });
    if (path === `/gists/${GIST}/comments`) return json([]);
    return json({ message: "not mocked" }, 404);
  });
}

// Each route with the element that shows it has finished rendering (the engine is loaded once, by the first route).
const ROUTES: { hash: string; ready: (page: Page) => ReturnType<Page["getByRole"]> }[] = [
  { hash: "#/", ready: (page) => page.getByRole("heading", { name: "Agentic patterns" }) },
  { hash: "#/models", ready: (page) => page.getByRole("heading", { name: "Models", exact: true }) },
  { hash: "#/experiments", ready: (page) => page.getByRole("heading", { name: "Experiments", exact: true }) },
  { hash: "#/leaderboard", ready: (page) => page.getByRole("heading", { name: "Leaderboard", exact: true }) },
  { hash: "#/runs", ready: (page) => page.getByRole("heading", { name: "Runs", exact: true }) },
  { hash: "#/board", ready: (page) => page.getByRole("table") },
  { hash: "#/board/overall", ready: (page) => page.getByRole("table") },
  { hash: `#/claim/gist/${GIST}@${REV}`, ready: (page) => page.getByRole("heading", { name: "Beat this setup" }) },
];

test.skip(({ browserName }) => browserName !== "chromium", "one browser is enough for the color math");
test.skip(!process.env.CLAIM_E2E, "needs the built site: make web, then npm run test:a11y");
test.setTimeout(300_000);

test("the main routes have no color-contrast violations, light and dark", async ({ page }) => {
  await mockData(page);
  await page.goto(`${SITE}#/`);
  await expect(ROUTES[0]!.ready(page)).toBeVisible({ timeout: 180_000 });  // Pyodide loads here

  const found: string[] = [];
  for (const theme of ["light", "dark"]) {
    for (const route of ROUTES) {
      await page.goto(`${SITE}${route.hash}`);
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      await expect(route.ready(page)).toBeVisible({ timeout: 60_000 });
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 60_000 });
      const results = await new AxeBuilder({ page }).withRules(["color-contrast"]).analyze();
      for (const violation of results.violations) {
        for (const node of violation.nodes) found.push(`${route.hash} [${theme}] ${node.target.join(" ")}: ${node.any[0]?.message ?? ""}`);
      }
    }
  }
  expect(found).toEqual([]);
});
