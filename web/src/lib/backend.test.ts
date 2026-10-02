import { afterEach, describe, expect, it, vi } from "vitest";

import { detectLocalBackend, exchangeSession } from "./backend";

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
