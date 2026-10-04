import { describe, expect, it } from "vitest";

import { SANDBOX_DENIED_CALLS, SANDBOX_DENIED_STORAGE, denySandboxNetwork } from "./pyodide";

describe("sandbox lock-down", () => {
  it("removes network APIs and same-origin storage, permanently", () => {
    const scope: Record<string, unknown> = { fetch: () => "network", indexedDB: { open: () => "bundles" }, caches: {}, postMessage: () => "ok" };
    denySandboxNetwork(scope);
    for (const name of SANDBOX_DENIED_CALLS) expect(() => (scope[name] as () => unknown)()).toThrow(/disabled/);
    for (const name of SANDBOX_DENIED_STORAGE) expect(() => scope[name]).toThrow(/disabled/);
    expect(() => { scope.indexedDB = {}; }).toThrow();                // cannot be put back
    expect(() => Object.defineProperty(scope, "fetch", { value: () => "again" })).toThrow();
    expect((scope.postMessage as () => string)()).toBe("ok");      // replies to the pool still work
  });
});
