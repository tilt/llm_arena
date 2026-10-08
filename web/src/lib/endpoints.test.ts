import { describe, expect, it } from "vitest";

import type { CatalogItem } from "./backend";
import { endpointHint, endpointIdProblem, endpointUrlProblem, groupOf } from "./endpoints";

describe("endpoint form rules (mirroring llm/spec.py)", () => {
  it("accepts names that cannot shadow a provider", () => {
    expect(endpointIdProblem("gpu-box")).toBe("");
    expect(endpointIdProblem("GPU")).not.toBe("");
    expect(endpointIdProblem("-x")).not.toBe("");
    expect(endpointIdProblem("openai")).toContain("reserved");
  });

  it("never lets a key travel in cleartext across the internet", () => {
    expect(endpointUrlProblem("https://llm.example.com/v1", true)).toBe("");
    expect(endpointUrlProblem("http://llm.example.com/v1", false)).toBe("");  // no key, nothing to protect
    expect(endpointUrlProblem("http://llm.example.com/v1", true)).toContain("https");
    expect(endpointUrlProblem("http://52.28.1.9:8000/v1", true)).toContain("https");
    for (const local of ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://192.168.1.20:8000/v1", "http://10.1.2.3/v1", "http://[::1]:8000/v1"]) {
      expect(endpointUrlProblem(local, true)).toBe("");
    }
  });

  it("keeps credentials and queries out of the URL", () => {
    expect(endpointUrlProblem("https://user:pw@llm.example.com/v1", false)).not.toBe("");
    expect(endpointUrlProblem("https://llm.example.com/v1?key=x", false)).not.toBe("");
    expect(endpointUrlProblem("ftp://llm.example.com/v1", false)).not.toBe("");
    expect(endpointUrlProblem("llm.example.com", false)).not.toBe("");
  });
});

describe("endpoint display", () => {
  it("explains blocked requests in browser mode only", () => {
    expect(endpointHint("TransportError: JsException: TypeError: Failed to fetch", "browser")).toContain("CORS");
    expect(endpointHint("TransportError: JsException: TypeError: Failed to fetch", "local")).toBe("");
    expect(endpointHint("RuntimeError: HTTP 401: invalid key", "browser")).toBe("");
  });

  it("groups models by endpoint name", () => {
    expect(groupOf({ source: "openai_compatible", endpoint: "gpu-box" } as CatalogItem)).toBe("gpu-box");
    expect(groupOf({ source: "openai" } as CatalogItem)).toBe("openai");
  });
});
