import { describe, expect, it } from "vitest";

import {
  credentialStorageAllowed,
  enforceCredentialStorage,
  readRememberedEndpoints,
  readRememberedKeys,
  writeRememberedEndpoints,
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

  it("drops remembered endpoints on an untrusted origin, so a shared origin never learns their URLs", () => {
    const storage = new MemoryStorage();
    storage.setItem("llm-arena.endpoints", JSON.stringify({ "gpu-box": { base_url: "https://llm.example.com/v1" } }));
    enforceCredentialStorage("https://tilt.github.io", storage, new MemoryStorage(), "https://arena.example");
    expect(storage.getItem("llm-arena.endpoints")).toBeNull();
  });

  it("remembers valid endpoints with their key on the trusted origin", () => {
    const storage = new MemoryStorage();
    writeRememberedEndpoints({ "gpu-box": { base_url: "https://llm.example.com/v1", key: "sk-endpoint" } }, storage);
    storage.setItem("llm-arena.endpoints", JSON.stringify({
      ...JSON.parse(storage.getItem("llm-arena.endpoints")!), broken: { url: 1 }, nothing: null,
    }));
    expect(readRememberedEndpoints(storage)).toEqual({ "gpu-box": { base_url: "https://llm.example.com/v1", key: "sk-endpoint" } });
    writeRememberedEndpoints({}, storage);
    expect(storage.getItem("llm-arena.endpoints")).toBeNull();
  });
});
