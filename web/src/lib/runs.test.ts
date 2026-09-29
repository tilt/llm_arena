import { describe, expect, it } from "vitest";

import type { Leaderboard, LeaderboardEntry } from "./contracts";
import { roleLines, scenarioSummaries, setupPolicy } from "./leaderboard";
import { ago, elapsed } from "./runs.svelte";

describe("run times", () => {
  const now = Date.parse("2026-09-29T12:00:00");
  it("says how long ago a run started", () => {
    expect(ago("2026-09-29 11:59:40", now)).toBe("just now");
    expect(ago("2026-09-29 11:45:00", now)).toBe("15 min ago");
    expect(ago("2026-09-29 09:00:00", now)).toBe("3 h ago");
    expect(ago("2026-09-26 12:00:00", now)).toBe("3 d ago");
    expect(ago("", now)).toBe("");
  });
  it("formats elapsed time", () => {
    expect(elapsed(now / 1000 - 75, now)).toBe("1 min 15 s");
    expect(elapsed(now / 1000 - 3725, now)).toBe("1 h 2 min");
  });
});

describe("leaderboard summaries", () => {
  const entry = (config: string, rate: number): LeaderboardEntry => ({
    rank: 1, fingerprint: config, config, names: [config], runs: ["r1", "r2"], trials: 4, tasks: 2, pass_rate: rate, ci_low: 0,
    ci_high: 1, mean_cost_usd: 0, mean_tokens: 0, latency_p50_s: 1,
    setup: { roles: { critic: { model: "qwen3:4b", reasoning_effort: "none" } }, decisions: { policy: "ollaya", control: "gate", ollaya_model: "winnow:e4b" } },
  });
  it("gives one card per scenario with its leader, and never ranks across scenarios", () => {
    const boards: Leaderboard[] = [
      { scenario: "a", scenario_version: "1", tasks: 2, entries: [entry("best", 0.9), entry("next", 0.5)] },
      { scenario: "b", scenario_version: "1", tasks: 2, entries: [] },
    ];
    const cards = scenarioSummaries(boards);
    expect(cards.map((c) => [c.scenario, c.leader.config, c.setups, c.runs])).toEqual([["a", "best", 2, 2]]);
  });
  it("describes setups readably", () => {
    expect(roleLines(entry("x", 1))).toEqual([{ role: "critic", model: "qwen3:4b (no thinking)" }]);
    expect(setupPolicy(entry("x", 1))).toBe("ollaya winnow:e4b · gate");
  });
});
