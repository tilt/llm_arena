// The claims board on the built site (browser mode): it renders from board.json before the in-browser engine is
// ready, switches feeds, keeps rate and confidence visible on a phone, and passes an axe scan. Run `make web` first.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const SITE = "http://127.0.0.1:4175/";

const row = (hash: string, people: number, model: string, rate: number, low: number, extra: Record<string, unknown> = {}) => ({
  gist_id: "a".repeat(32), revision: "b".repeat(40), claim_hash: hash.repeat(64), owner: "alice", scenario: "email_assistant",
  scenario_version: "2", state: "ok", runnable: true, roles: { agent: { provider: "openai", model, backend: "auto",
    tool_mode: "native", temperature: 0.2, reasoning_effort: null, max_tokens: 1024 } },
  decisions: null, judge: null, tier: people >= 3 ? "verified" : people ? "reproduced" : "claimed", people,
  reproducers: Array.from({ length: people }, (_, i) => `user${i}`), rate, low, high: Math.min(1, rate + 0.06), tasks: 11,
  step_credit: 0.9, criteria: { state_correct: { passed: 20, graded: 22 }, answer_correct: { passed: 18, graded: 22 } },
  cost_usd_per_task: 0.004, cost_source: people ? "reproduced" : "claimed", claimed_rate: rate, reproduce_usd: 0.05,
  made_at: "2026-10-11T10:00:00+00:00", refreshed_at: "2026-10-12T06:17:00+00:00", notes: [], ...extra,
});

const BOARD = {
  board_version: 1, built_at: new Date().toISOString(), claims: 4, reproductions: 6,
  scenarios: [{
    scenario: "email_assistant", version: "2",
    ranked: [row("1", 4, "gpt-4.1", 0.92, 0.84), row("2", 1, "gpt-4.1-mini", 0.86, 0.79,
      { notes: [{ kind: "removed_after_recorded", count: 1, detail: "" }] })],
    unreproduced: [row("3", 0, "claude-sonnet-4.5", 1.0, 0.74)],
    merged: ["1".repeat(64), "2".repeat(64), "3".repeat(64)], older: [],
  }],
  overall: {
    reproduced: { all: [{ provider: "openai", model: "gpt-4.1", reasoning_effort: null, tool_mode: "native", score: 0, raw: 0.92,
      setups: 1, scenarios: 1, only_claim: 0, claims: ["1".repeat(64)] }] },
    merged: {},
  },
  delisted: [], ledger_lines: 6, ledger_head: "0".repeat(64), registry_entries: 4, registry_head: "0".repeat(64),
};

async function serveBoard(page: Page): Promise<void> {
  await page.route("**/board.json", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify(BOARD) }));
}

test.skip(!process.env.CLAIM_E2E, "needs the built site (npm run test:board)");

test("the board renders from board.json before the engine is ready, and the switch merges the lists", async ({ page }) => {
  await serveBoard(page);
  await page.goto(`${SITE}#/board`);
  await expect(page.getByRole("heading", { name: "Claims board" })).toBeVisible();
  await expect(page.getByText("Best reproduced on email_assistant: gpt-4.1, 92% [84–98], reproduced by 4 people.")).toBeVisible({ timeout: 3000 });
  const table = page.getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(4);  // header, two ranked rows, one note row
  await expect(page.getByText("1 reproduction removed by the author after the board recorded it (still counted)")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Waiting for a first reproduction (1)" })).toBeVisible();
  await page.getByRole("radio", { name: "Include unreproduced" }).check();
  await expect(page.getByText("Showing 3 setups")).toBeAttached();
  await page.getByRole("link", { name: "Overall" }).click();
  await expect(page).toHaveURL(/#\/board\/overall$/);
  await expect(page.getByText("level with the best, on average")).toBeVisible();
});

test("on a phone each row keeps rate and confidence visible, with the rest under Details", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await serveBoard(page);
  await page.goto(`${SITE}#/board/email_assistant`);
  const first = page.getByRole("row", { name: /^1 agent · gpt-4\.1 / });
  await expect(first.getByText("92% [84–98]")).toBeVisible();
  await expect(first.getByText("verified · 4 people")).toBeVisible();
  await expect(first.locator("td.wide").first()).toBeHidden();
  await first.getByText("Details").click();
  await expect(first.locator("td.phone").getByRole("link", { name: "Beat this" })).toBeVisible();
});

test("the board passes an axe scan", async ({ page }) => {
  await serveBoard(page);
  await page.goto(`${SITE}#/board/email_assistant`);
  await expect(page.getByRole("table")).toBeVisible();
  const results = await new AxeBuilder({ page }).include(".board").analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
});
