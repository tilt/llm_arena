import { afterEach, describe, expect, it, vi } from "vitest";
import {
  GitHub, GitHubFailure, declaredAs, failureOf, failureText, fromBase64Url, inlineLink, nameProblem, parseClaimHash, postedNote, prefillName,
  previewOf, savePostedNote, seenIds, suggestName, toBase64Url,
} from "./claims";
import type { CatalogItem } from "./backend";
import type { ThreadRow } from "./contracts";
import { importId } from "./worker-backend";
import { keyRows } from "./keys";
import { NOT_PRICED, perMtok } from "./format";
import { policyOf, roleLinesOf } from "./leaderboard";
import { parse } from "./router.svelte";

const CLAIM = JSON.stringify({
  scenario: "email_assistant", scenario_version: "2", tasks: [{ id: "a", fp: "00000000" }],
  setup: { roles: { agent: { provider: "openai", model: "gpt-4.1-mini" }, critic: { provider: "self_hosted", model: "qwen3-14b" } } },
  result: { pass_rate: 0.9, cost_usd_per_task: 0.004 },
});

describe("claim links", () => {
  it("parses gist links and refuses anything else", () => {
    const id = "a".repeat(32), rev = "b".repeat(40);
    expect(parseClaimHash(`gist/${id}@${rev}`)).toEqual({ kind: "gist", id, revision: rev });
    expect(parseClaimHash(`gist/${"A".repeat(32)}@${rev}`)).toBeNull();
    expect(parseClaimHash(`gist/${id}@short`)).toBeNull();
    expect(parseClaimHash("not base64!")).toBeNull();
    expect(parse(`#/claim/gist/${id}@${rev}`)).toEqual({ name: "claim", link: { kind: "gist", id, revision: rev } });
  });

  it("round-trips a claim through a link without a gist, unicode included", () => {
    const text = JSON.stringify({ note: "Grüße ✓" });
    expect(fromBase64Url(toBase64Url(text))).toBe(text);
    const link = inlineLink(CLAIM, "https://x/");
    expect(parse(link.slice("https://x/".length))).toEqual({ name: "claim", link: { kind: "inline", text: CLAIM } });
  });
});

describe("preview before the engine validates", () => {
  it("reads only typed, length-capped fields", () => {
    expect(previewOf(CLAIM)).toEqual({
      scenario: "email_assistant", version: "2", tasks: 1, passRate: 0.9, costPerTask: 0.004,
      roles: [{ role: "agent", model: "openai:gpt-4.1-mini" }, { role: "critic", model: "self-hosted qwen3-14b" }],
    });
  });

  it("shows nothing for malformed or hostile claims", () => {
    const base = JSON.parse(CLAIM) as Record<string, unknown>;
    for (const bad of [
      "not json", "null", JSON.stringify({ ...base, scenario: 7 }), JSON.stringify({ ...base, scenario: "x".repeat(65) }),
      JSON.stringify({ ...base, result: { pass_rate: 2, cost_usd_per_task: 0 } }),
      JSON.stringify({ ...base, setup: { roles: { agent: { provider: "openai", model: "<script>".repeat(40) } } } }),
      JSON.stringify({ ...base, tasks: [] }),
    ]) expect(previewOf(bad)).toBeNull();
  });
});

describe("self-hosted names", () => {
  it("suggests a valid name from a server id", () => {
    expect(suggestName("qwen3:14b")).toBe("qwen3-14b");
    expect(suggestName("Qwen/Qwen3-14B-AWQ")).toBe("qwen3-14b-awq");
    expect(suggestName("///")).toBe("model");
    expect(nameProblem("qwen3-14b")).toBe("");
    expect(nameProblem("Qwen3")).not.toBe("");
  });

  const item = (ref: string, source: string, model: string, endpoint?: string) =>
    ({ ref, source, endpoint, spec: { model } } as unknown as CatalogItem);

  it("prefills the remembered name, then the same id's name on another server, then a suggestion", () => {
    const box = item("gpu-box:Qwen3-14B", "openai_compatible", "Qwen3-14B", "gpu-box");
    const laptop = item("laptop:Qwen3-14B", "openai_compatible", "Qwen3-14B", "laptop");
    expect(prefillName(box, { "gpu-box:Qwen3-14B": "qwen3-14b-awq" })).toBe("qwen3-14b-awq");
    expect(prefillName(laptop, { "gpu-box:Qwen3-14B": "qwen3-14b-awq" })).toBe("qwen3-14b-awq");
    expect(prefillName(laptop, {})).toBe("qwen3-14b");
    const cloud = item("openai:gpt-4.1-mini", "openai", "gpt-4.1-mini");
    expect(declaredAs("qwen3-14b", [box, laptop, cloud], { "laptop:Qwen3-14B": "qwen3-14b" }).map((m) => m.ref)).toEqual(["laptop:Qwen3-14B"]);
  });
});

describe("GitHub failures", () => {
  const response = (status: number, headers: Record<string, string> = {}) => ({ status, headers: { get: (n: string) => headers[n] ?? null } });

  it("tells each state apart, like the local adapter", () => {
    expect(failureOf(response(404), false).kind).toBe("not_found");
    expect(failureOf(response(503), false).kind).toBe("server");
    expect(failureOf(response(403, { "x-ratelimit-remaining": "0" }), false).kind).toBe("rate_limited");
    expect(failureOf(response(403, { "x-ratelimit-remaining": "0" }), true).kind).toBe("throttled");
    const wait = failureOf(response(429, { "retry-after": "30" }), true);
    expect([wait.kind, wait.retryAfterS]).toEqual(["throttled", 30]);
    expect(failureOf(response(403), true).kind).toBe("unauthorized");
    expect(failureText(new GitHubFailure("rate_limited", "x", 120))).toContain("2 min");
  });
});

describe("per-browser notes", () => {
  it("degrade to nothing when storage throws", () => {
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(() => savePostedNote("r1", { gist_id: "g", comment_id: 1, claim_hash: "h", posted_at: "t" }, broken)).not.toThrow();
    expect(postedNote("r1", broken)).toBeNull();
  });

  it("round-trip through working storage", () => {
    const data: Record<string, string> = {};
    const store = { getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => { data[k] = v; } };
    savePostedNote("r1", { gist_id: "g", comment_id: 7, claim_hash: "h", posted_at: "t" }, store);
    expect(postedNote("r1", store)?.comment_id).toBe(7);
  });

  it("lists only counted (or the author's) reproductions as seen", () => {
    const rows = [{ comment_id: 1, status: "counted" }, { comment_id: 2, status: "rejected" }, { comment_id: 3, status: "author" }] as ThreadRow[];
    expect(seenIds(rows)).toEqual([1, 3]);
  });
});

describe("shared helpers the claim page reuses", () => {
  it("words key rows per provider and filters them", () => {
    const rows = keyRows({ openai: "env", github: "missing" });
    expect(rows.map((r) => [r.label, r.placeholder])).toEqual([["OpenAI", "paste key"], ["GitHub (claims)", "paste token"]]);
    expect(rows[1]!.warning).toContain("gists");
    expect(keyRows({ openai: "env", github: "missing" }, ["github"]).map((r) => r.provider)).toEqual(["github"]);
  });

  it("calls an unpriced model not priced, never free", () => {
    expect(perMtok(0, 0)).toBe(NOT_PRICED);
    expect(perMtok(0.4, 1.6)).toBe("$0.4 / $1.6");
  });

  it("words a claim's setup like the leaderboard", () => {
    expect(roleLinesOf({ roles: { agent: { model: "gpt-4.1-mini", reasoning_effort: "none" } } }))
      .toEqual([{ role: "agent", model: "gpt-4.1-mini (no thinking)" }]);
    expect(policyOf({ decisions: null })).toBe("the agent decides");
  });

  it("gives an imported run a free id instead of overwriting one", () => {
    expect(importId("r1", new Set())).toBe("r1");
    expect(importId("r1", new Set(["r1", "r1-imported-1"]))).toBe("r1-imported-2");
  });
});

describe("GitHub plumbing", () => {
  afterEach(() => vi.unstubAllGlobals());
  const id = "a".repeat(32), rev = "b".repeat(40);

  it("maps the local server's failure detail and reads at most three pages, none for an empty thread", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes("comments?page=")) return new Response("[]", { status: 200 });
      return new Response(JSON.stringify({ detail: { kind: "rate_limited", message: "m", retry_after_s: 120 } }), { status: 429 });
    }));
    const gh = new GitHub("local");
    await expect(gh.claim(id, rev)).rejects.toMatchObject({ kind: "rate_limited", retryAfterS: 120 });
    await gh.thread(id, 1000);
    expect(calls.filter((u) => u.includes("comments?page="))).toHaveLength(3);
    expect(await gh.thread(id, 0)).toEqual([]);
    expect(calls.filter((u) => u.includes("comments?page="))).toHaveLength(3);
  });

  it("checks ids and the token before any request", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(new GitHub("browser").post(id, "x")).rejects.toMatchObject({ kind: "unauthorized" });
    const withToken = new GitHub("browser", () => "tok");
    await expect(withToken.post("../repos/o/r/issues/1", "x")).rejects.toMatchObject({ kind: "invalid" });
    await expect(withToken.claim(id, `../../gists/${id}/${rev}`)).rejects.toMatchObject({ kind: "invalid" });
    await expect(withToken.comment(id, Number.NaN)).rejects.toMatchObject({ kind: "invalid" });
    expect(fetch).not.toHaveBeenCalled();
  });
});
