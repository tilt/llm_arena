import { describe, expect, it, vi } from "vitest";
import {
  OVERALL, answerLine, byText, defaultFeed, defaultTab, gapText, linkable, loadBoard, nextUpdate, normalize, noteText, rowsOf,
  saveFeed, storedFeed, submitHref, type Board,
} from "./board";
import type { Board as RawBoard, Row as RawRow } from "./contracts";
import { parse } from "./router.svelte";

const row = (hash: string, people: number, extra: Partial<RawRow> = {}): RawRow => ({
  gist_id: "a".repeat(32), revision: "b".repeat(40), claim_hash: hash, owner: "alice", scenario: "email_assistant",
  scenario_version: "2", state: "ok", roles: { agent: { provider: "openai", model: "gpt-4.1-mini" } } as RawRow["roles"],
  tier: people >= 3 ? "verified" : people ? "reproduced" : "claimed", people, rate: 0.86, low: 0.79, high: 0.91,
  tasks: 11, step_credit: 0.9, cost_usd_per_task: 0.004, cost_source: "claimed", claimed_rate: 0.9,
  reproduce_usd: 0.05, made_at: "2026-10-11", refreshed_at: "2026-10-12T06:00:00+00:00", ...extra,
});

const raw = (scenarios: RawBoard["scenarios"]): RawBoard => ({
  board_version: 1, built_at: "2026-10-12T06:17:00+00:00", claims: 3, reproductions: 4, scenarios,
});

describe("loading board.json", () => {
  it("fills defaulted fields, and asks for a reload on an unknown format", async () => {
    const ok = vi.fn(async () => new Response(JSON.stringify(raw([{ scenario: "email_assistant", version: "2", ranked: [row("1", 2)] }]))));
    const loaded = await loadBoard("/", ok as unknown as typeof fetch);
    expect(loaded.state).toBe("ok");
    const board = (loaded as { board: Board }).board;
    expect(board.scenarios[0]!.unreproduced).toEqual([]);
    expect(board.scenarios[0]!.ranked[0]!.notes).toEqual([]);
    const newer = vi.fn(async () => new Response(JSON.stringify({ ...raw([]), board_version: 2 })));
    expect((await loadBoard("/", newer as unknown as typeof fetch)).state).toBe("outdated");
    const missing = vi.fn(async () => new Response("", { status: 404 }));
    expect((await loadBoard("/", missing as unknown as typeof fetch)).state).toBe("missing");
    const offline = vi.fn(async () => { throw new TypeError("offline"); });
    expect((await loadBoard("/", offline as unknown as typeof fetch)).state).toBe("error");
  });
});

describe("tabs and the merge switch", () => {
  const board = normalize(raw([
    { scenario: "support_desk", version: "1", ranked: [row("1", 1)], unreproduced: [row("2", 0), row("3", 0)], merged: ["2", "1", "3"] },
    { scenario: "email_assistant", version: "2", ranked: [row("4", 2), row("5", 1)] },
    { scenario: "shop_codeact", version: "2", unreproduced: [row("6", 0)], merged: ["6"] },
  ]));

  it("opens the scenario with the most reproduced claims, ties by claims then name (3A)", () => {
    expect(defaultTab(board)).toBe("email_assistant");
    expect(defaultTab(normalize(raw([])))).toBe(OVERALL);
  });

  it("defaults to merged only while a scenario has nothing reproduced (D3)", () => {
    expect(defaultFeed(board, "shop_codeact")).toBe("merged");
    expect(defaultFeed(board, "support_desk")).toBe("reproduced");
    expect(rowsOf(board.scenarios[0]!, "merged").map((r) => r.claim_hash)).toEqual(["2", "1", "3"]);
    expect(rowsOf(board.scenarios[0]!, "reproduced").map((r) => r.claim_hash)).toEqual(["1"]);
  });

  it("remembers the choice per scenario and survives storage that throws (13A)", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    saveFeed("support_desk", "merged", storage);
    expect(storedFeed("support_desk", storage)).toBe("merged");
    expect(storedFeed("email_assistant", storage)).toBeNull();
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(storedFeed("x", broken)).toBeNull();
    expect(() => saveFeed("x", "merged", broken)).not.toThrow();
  });
});

describe("words", () => {
  it("states rank 1 as the answer line, or calls for reproductions (2A)", () => {
    const [support, , shop] = normalize(raw([
      { scenario: "support_desk", version: "1", ranked: [row("1", 5)] },
      { scenario: "x", version: "1" },
      { scenario: "shop_codeact", version: "2", unreproduced: [row("6", 0), row("7", 0)] },
    ])).scenarios;
    expect(answerLine(support!)).toBe("Best reproduced on support_desk: gpt-4.1-mini, 86% [79–91], reproduced by 5 people.");
    expect(answerLine(shop!)).toBe("No reproduced claims yet: the 2 claims below wait for a first reproduction.");
  });

  it("explains witness notes and disables links where the claim page can't load", () => {
    const note = { kind: "removed_after_recorded" as const, count: 1, detail: "" };
    expect(noteText(note)).toBe("1 reproduction removed by the author after the board recorded it (still counted)");
    expect(noteText({ kind: "partial_thread", count: 1, detail: "150" })).toBe("based on 1 of 150 comments");
    const gone = normalize(raw([{ scenario: "s", version: "1", ranked: [row("1", 1, { notes: [{ kind: "gist_deleted" }], runnable: false })] }]));
    expect(linkable(gone.scenarios[0]!.ranked[0]!)).toBe(false);
    expect(gapText({ score: -0.04 } as never)).toBe("4 pts behind the best, on average");
    expect(gapText({ score: 0 } as never)).toBe("level with the best, on average");
  });

  it("names who reproduced a row, up to three people and a count of the rest (R2-4)", () => {
    const named = (n: number) => normalize(raw([{ scenario: "s", version: "1",
      ranked: [row("1", n, { reproducers: Array.from({ length: n }, (_, i) => `user${i}`) })] }])).scenarios[0]!.ranked[0]!;
    expect(byText(named(2))).toBe("user0, user1");
    expect(byText(named(5))).toBe("user0, user1, user2 and 2 more");
  });

  it("prefills the submission form and estimates the next update at :17 every 6 hours", () => {
    expect(submitHref("a".repeat(32), "b".repeat(40))).toBe(
      `https://github.com/tilt/llm_arena/issues/new?template=claim.yml&gist=${"a".repeat(32)}&revision=${"b".repeat(40)}`);
    const board = normalize(raw([]));
    expect(nextUpdate(board, new Date("2026-10-12T07:00:00Z")).toISOString()).toBe("2026-10-12T12:17:00.000Z");
    expect(nextUpdate(board, new Date("2026-10-12T23:30:00Z")).toISOString()).toBe("2026-10-13T00:17:00.000Z");
  });

  it("routes every board tab to its own address (3A)", () => {
    expect(parse("#/board")).toEqual({ name: "board", tab: undefined });
    expect(parse("#/board/overall")).toEqual({ name: "board", tab: "overall" });
    expect(parse("#/board/email_assistant")).toEqual({ name: "board", tab: "email_assistant" });
  });
});
