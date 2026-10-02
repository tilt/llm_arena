import { describe, expect, it } from "vitest";

import {
  credentialStorageAllowed,
  enforceCredentialStorage,
  readRememberedKeys,
  writeRememberedKeys,
} from "./credential-storage";

class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

describe("browser credential origin", () => {
  it("requires an exact non-empty build-time origin", () => {
    expect(credentialStorageAllowed("https://arena.example", "https://arena.example")).toBe(true);
    expect(credentialStorageAllowed("https://arena.example", "")).toBe(false);
    expect(credentialStorageAllowed("https://arena.example", "https://arena.example/path")).toBe(false);
    expect(credentialStorageAllowed("https://sub.arena.example", "https://arena.example")).toBe(false);
  });

  it("deletes an untrusted legacy entry without parsing it and reports removal once", () => {
    const keys = new MemoryStorage();
    const notices = new MemoryStorage();
    keys.setItem("llm-arena.keys", "{definitely-not-json");
    expect(enforceCredentialStorage(
      "https://lookalike.example",
      keys,
      notices,
      "https://arena.example",
    )).toEqual({ canRemember: false, removedLegacyKeys: true });
    expect(keys.getItem("llm-arena.keys")).toBeNull();
    expect(enforceCredentialStorage(
      "https://lookalike.example",
      keys,
      notices,
      "https://arena.example",
    ).removedLegacyKeys).toBe(false);
  });

  it("preserves and validates remembered values only on the trusted origin", () => {
    const keys = new MemoryStorage();
    keys.setItem("llm-arena.keys", JSON.stringify({ openai: "key", invalid: 42 }));
    expect(enforceCredentialStorage(
      "https://arena.example",
      keys,
      new MemoryStorage(),
      "https://arena.example",
    )).toEqual({ canRemember: true, removedLegacyKeys: false });
    expect(readRememberedKeys(keys)).toEqual({ openai: "key" });
    writeRememberedKeys({}, keys);
    expect(keys.getItem("llm-arena.keys")).toBeNull();
  });
});
