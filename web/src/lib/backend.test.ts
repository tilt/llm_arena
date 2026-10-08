import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpBackend, detectLocalBackend, exchangeSession } from "./backend";

afterEach(() => vi.unstubAllGlobals());

describe("local session detection", () => {
  it("distinguishes a locked server from an absent server", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ auth: "required" }),
      { status: 401, headers: { "content-type": "application/json" } },
    )));
    const backend = await detectLocalBackend();
    expect(backend?.locked).toBe(true);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("not listening")));
    expect(await detectLocalBackend()).toBeNull();
  });

  it("exchanges the fragment token without putting it in a URL", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    await exchangeSession("one-time-token");
    expect(fetch).toHaveBeenCalledWith("/api/session", expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({ token: "one-time-token" }),
    }));
  });
});

describe("endpoints on the local app", () => {
  it("saves, lists and removes endpoints over the API", async () => {
    const view = { id: "gpu-box", base_url: "https://llm.example.com/v1", key: "session" };
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json(view))
      .mockResolvedValueOnce(Response.json([view]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    const backend = new HttpBackend();
    const body = { base_url: "https://llm.example.com/v1", key: "sk-endpoint" };
    expect(await backend.saveEndpoint("gpu-box", body)).toEqual(view);
    expect(await backend.endpoints()).toEqual([view]);
    await backend.removeEndpoint("gpu-box");
    expect(fetch.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      ["/api/endpoints/gpu-box", "PUT"], ["/api/endpoints", "GET"], ["/api/endpoints/gpu-box", "DELETE"],
    ]);
    expect((fetch.mock.calls[0]![1] as RequestInit).body).toBe(JSON.stringify(body));
  });
});
