import { describe, expect, it } from "vitest";

import { SANDBOX_DENIED_CALLS, SANDBOX_DENIED_STORAGE, denySandboxNetwork } from "./pyodide";

describe("sandbox lock-down", () => {
  it("removes direct and inherited capabilities permanently", () => {
    const inherited: Record<string, unknown> = {
      fetch: () => "network",
      indexedDB: { open: () => "bundles" },
      caches: {},
    };
    const scope = Object.assign(Object.create(inherited) as Record<string, unknown>, {
      postMessage: () => "ok",
      BroadcastChannel: () => "other tab",
    });
    denySandboxNetwork(scope);
    for (const name of SANDBOX_DENIED_CALLS) expect(() => (scope[name] as () => unknown)()).toThrow(/disabled/);
    for (const name of SANDBOX_DENIED_STORAGE) expect(() => scope[name]).toThrow(/disabled/);
    expect(() => (Object.getOwnPropertyDescriptor(inherited, "fetch")!.value as () => unknown)()).toThrow(/disabled/);
    expect(() => Object.getOwnPropertyDescriptor(inherited, "indexedDB")!.get!.call(scope)).toThrow(/disabled/);
    expect(() => { scope.indexedDB = {}; }).toThrow();
    expect(() => Object.defineProperty(scope, "fetch", { value: () => "again" })).toThrow();
    expect((scope.postMessage as () => string)()).toBe("ok");
  });
});
