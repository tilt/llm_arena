// The shared-claim loop end to end on the built site (browser mode, the real Pyodide engine): open a claim link,
// see it before the engine is ready, add a key, re-run the claimed setup, post the reproduction, and see it counted
// on reload. GitHub and OpenAI are mocked; Pyodide itself loads from its pinned CDN files. Run `make web` first.
import { readFileSync } from "node:fs";
import { expect, test, type Page, type Route } from "@playwright/test";

const SITE = "http://127.0.0.1:4175/";
const GIST = "a".repeat(32);
const REV = "b".repeat(40);
const vector = JSON.parse(readFileSync(new URL("../../../contracts/conformance/claim-mixed-thread.json", import.meta.url), "utf8")) as {
  input: { claim: string };
};
const CLAIM = vector.input.claim;
const GOOD_SQL = "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
  + "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```";

interface Posted { body: string; auth: string | null }

async function mockGitHub(page: Page, thread: { id: number; user: { login: string }; created_at: string; updated_at: string; body: string }[],
  posted: Posted[], firstRequestAt: number[]) {
  await page.context().route("https://api.github.com/**", async (route: Route) => {
    const url = new URL(route.request().url());
    firstRequestAt.push(Date.now());
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type, accept",
      "access-control-allow-methods": "GET, POST, OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });  // like api.github.com
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body),
      headers: cors });
    if (url.pathname === `/gists/${GIST}/${REV}`) return json({ files: { "claim.json": { content: CLAIM } }, owner: { login: "alice" } });
    if (url.pathname === `/gists/${GIST}`) return json({ history: [{ version: REV }], comments: thread.length, html_url: "https://gist.github.com/x" });
    if (url.pathname === `/gists/${GIST}/comments` && route.request().method() === "POST") {
      const body = (route.request().postDataJSON() as { body: string }).body;
      posted.push({ body, auth: route.request().headers()["authorization"] ?? null });
      return json({ id: 99, user: { login: "bob" }, created_at: "2026-10-10T12:00:00Z", updated_at: "2026-10-10T12:00:00Z", body,
        html_url: "https://gist.github.com/x#c99" }, 201);
    }
    if (url.pathname === `/gists/${GIST}/comments`) return json(thread);
    if (url.pathname === `/gists/${GIST}/comments/99`) return json(thread.find((c) => c.id === 99) ?? {}, thread.some((c) => c.id === 99) ? 200 : 404);
    return json({ message: "not mocked" }, 404);
  });
}

async function mockOpenAI(page: Page) {
  await page.context().route("https://api.openai.com/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body),
      headers: { "access-control-allow-origin": "*" } });
    if (url.pathname === "/v1/models") return json({ data: [{ id: "gpt-4.1-mini" }, { id: "gpt-4.1-nano" }] });
    const text = route.request().postData() ?? "";
    const content = text.includes("verdict") ? '{"verdict": "accept", "issues": []}' : GOOD_SQL;
    return json({ choices: [{ message: { role: "assistant", content }, finish_reason: "stop" }], usage: { prompt_tokens: 100, completion_tokens: 50 },
      model: "gpt-4.1-mini" });
  });
}

test.skip(({ browserName }) => browserName !== "chromium", "one browser is enough for the app flow");
test.setTimeout(240_000);

test("a claim link is reproduced, posted and counted", async ({ page }) => {
  const thread: Parameters<typeof mockGitHub>[1] = [];
  const posted: Posted[] = [];
  const githubAt: number[] = [];
  await mockGitHub(page, thread, posted, githubAt);
  await mockOpenAI(page);
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") problems.push(message.text()); });
  await page.goto(`${SITE}#/claim/gist/${GIST}@${REV}`);

  // Before the engine: the guarded preview, fetched from GitHub while Pyodide still loads (2.1, D11).
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Claim: reflection_sql v1 · 2 tasks", { timeout: 30_000 });
  await expect(page.getByText("checking…").first()).toBeVisible();
  expect(githubAt.length).toBeGreaterThan(0);

  // Engine ready: validated view, Run disabled with its reason until a key is set (3.1, 6.2).
  const run = page.getByRole("button", { name: /Run claimed setup/ });
  await expect(page.getByRole("heading", { name: "Beat this setup" })).toBeVisible({ timeout: 180_000 });
  await expect(run).toBeDisabled();
  await expect(page.locator("#run-reasons")).toContainText("Add an OpenAI key");
  expect(await run.getAttribute("aria-describedby")).toBe("run-reasons");
  await page.getByLabel("OpenAI API key").fill("sk-test");
  await page.getByRole("button", { name: "Use" }).click();
  await expect(run).toBeEnabled({ timeout: 60_000 });

  // Run, then post with a token entered inline (2.3, 2.4).
  await run.click();
  const result = page.getByRole("heading", { name: "Your result" });
  await expect(result).toBeVisible({ timeout: 120_000 });
  await expect(result).toBeFocused();
  await page.getByRole("button", { name: "Post reproduction" }).click();
  await page.getByLabel(/GitHub token/).fill("ghp_test");
  await page.getByRole("button", { name: "Use" }).click();
  await page.getByRole("button", { name: "Post reproduction" }).click();
  await expect(page.getByText(/Posted ·/), problems.join("\n")).toBeVisible({ timeout: 30_000 });
  expect(posted).toHaveLength(1);
  expect(posted[0]!.body.startsWith("```arena-repro\n")).toBe(true);
  expect(posted[0]!.auth).toBe("Bearer ghp_test");

  // Reload: the thread now holds bob's reproduction, and the claim page counts it.
  thread.push({ id: 99, user: { login: "bob" }, created_at: "2026-10-10T12:00:00Z", updated_at: "2026-10-10T12:00:00Z", body: posted[0]!.body });
  await page.reload();
  await expect(page.getByText(/reproduced by 1 person/)).toBeVisible({ timeout: 180_000 });
  await expect(page.locator(".repro .pill").first()).toHaveText("counted");

  // Phone width: no horizontal scroll, Beat this after Setup (6.1).
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const setupBox = await page.getByRole("heading", { name: "Setup", exact: true }).boundingBox();
  const beatBox = await page.getByRole("heading", { name: "Beat this setup" }).boundingBox();
  expect(beatBox!.y).toBeGreaterThan(setupBox!.y);

  // Regression (R20): the Models page lists the same model keys with today's wording.
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${SITE}#/models`);
  await expect(page.getByLabel("OpenAI API key")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByLabel("Anthropic API key")).toBeVisible();
  await expect(page.getByText("GitHub (claims)")).toHaveCount(0); // Pages: the token lives on the claim page only (13.13)
});
