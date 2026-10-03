import { expect, test } from "@playwright/test";

interface SpikeResult {
  opaqueOrigin: boolean;
  localStorage: boolean;
  sessionStorage: boolean;
  fetch: boolean;
  websocket: boolean;
  eventSource: boolean;
  worker: { fetch: boolean; websocket: boolean; importScripts: boolean };
  assetDigests: string[];
  expectedDigests: string[];
  violations: string[];
}

test("opaque verified bootstrap denies storage and network in iframe and blob worker", async ({ page }) => {
  const browserRequests: string[] = [];
  const diagnostics: string[] = [];
  page.on("console", (message) => diagnostics.push(`${message.type()}: ${message.text()}`));
  page.on("pageerror", (error) => diagnostics.push(`pageerror: ${error.message}`));
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/canary")) browserRequests.push(request.url());
  });
  await page.goto("http://127.0.0.1:4174/");
  let result: SpikeResult;
  try {
    result = await page.evaluate(() => (window as typeof window & { __spikeResult: Promise<SpikeResult> }).__spikeResult);
  } catch (error) {
    const audit = await page.evaluate(() => (window as typeof window & { __isolationAudit: unknown }).__isolationAudit);
    throw new Error(`${String(error)}\naudit=${JSON.stringify(audit)}\nconsole=${JSON.stringify(diagnostics)}`);
  }
  expect(result).toMatchObject({
    opaqueOrigin: true,
    localStorage: true,
    sessionStorage: true,
    fetch: true,
    websocket: true,
    eventSource: true,
    worker: { fetch: true, websocket: true, importScripts: true },
  });
  expect(result.assetDigests).toEqual(result.expectedDigests);
  expect(result.violations).toContain("connect-src");
  const listenerHits = await (await page.request.get("http://127.0.0.1:4174/hits")).json();
  expect(listenerHits, `browser requests: ${JSON.stringify(browserRequests)}`).toEqual([]);
  const audit = await page.evaluate(() => (window as typeof window & {
    __isolationAudit: { verifiedBeforeIframe: boolean; rejectedMessages: number; bootstrapMechanism: string };
  }).__isolationAudit);
  expect(audit).toMatchObject({
    verifiedBeforeIframe: true,
    rejectedMessages: 1,
    bootstrapMechanism: "external-sri+csp-hash",
  });
});
