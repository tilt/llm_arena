import { expect, test } from "@playwright/test";

interface SpikeResult {
  opaqueOrigin: boolean;
  localStorage: boolean;
  sessionStorage: boolean;
  fetch: boolean;
  websocket: boolean;
  eventSource: boolean;
  dynamicImport: boolean;
  worker: {
    fetch: boolean;
    websocket: boolean;
    eventSource: boolean;
    importScripts: boolean;
    dynamicImport: boolean;
    localStorage: boolean;
    sessionStorage: boolean;
  };
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
    dynamicImport: true,
    worker: {
      fetch: true,
      websocket: true,
      eventSource: true,
      importScripts: true,
      dynamicImport: true,
      localStorage: true,
      sessionStorage: true,
    },
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

test("production lockdown denies worker prototype-chain recovery", async ({ page }) => {
  await page.goto("http://127.0.0.1:4174/");
  const result = await page.evaluate(async () => {
    const source = `
      import { SANDBOX_DENIED_CALLS, SANDBOX_DENIED_STORAGE, denySandboxNetwork }
        from "http://127.0.0.1:4174/sandbox-lockdown.ts";
      denySandboxNetwork();
      const blocked = (name, storage) => {
        const attempt = (descriptor) => {
          try {
            if (descriptor.get) descriptor.get.call(globalThis);
            else descriptor.value.call(globalThis);
            return false;
          } catch { return true; }
        };
        let direct;
        try {
          if (storage) globalThis[name]; else globalThis[name]();
          direct = false;
        } catch { direct = true; }
        const inherited = [];
        for (let owner = Object.getPrototypeOf(globalThis); owner; owner = Object.getPrototypeOf(owner)) {
          const descriptor = Object.getOwnPropertyDescriptor(owner, name);
          if (descriptor) inherited.push(attempt(descriptor));
        }
        return { direct, inherited };
      };
      const checks = Object.fromEntries([
        ...SANDBOX_DENIED_CALLS.map(name => [name, blocked(name, false)]),
        ...SANDBOX_DENIED_STORAGE.map(name => [name, blocked(name, true)]),
      ]);
      postMessage(checks);
    `;
    const url = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
    const worker = new Worker(url, { type: "module" });
    return await new Promise<Record<string, { direct: boolean; inherited: boolean[] }>>((resolve, reject) => {
      worker.onmessage = (event) => { worker.terminate(); URL.revokeObjectURL(url); resolve(event.data); };
      worker.onerror = (event) => { worker.terminate(); URL.revokeObjectURL(url); reject(new Error(event.message)); };
    });
  });
  for (const check of Object.values(result)) {
    expect(check.direct).toBe(true);
    expect(check.inherited.every(Boolean)).toBe(true);
  }
  expect(result.fetch.inherited.length).toBeGreaterThan(0);
  expect(result.indexedDB.inherited.length).toBeGreaterThan(0);
  expect(result.caches.inherited.length).toBeGreaterThan(0);
});
