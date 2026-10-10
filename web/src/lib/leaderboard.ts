// Leaderboard helpers: readable setups, and the per-scenario overview.
import type { Leaderboard, LeaderboardEntry } from "./contracts";

type RoleSpec = { model?: string; provider?: string; reasoning_effort?: string | null; tool_mode?: string };

/** "critic: qwen3:14b (no thinking)" per role, as recorded in the entry's setup. */
export function roleLines(entry: LeaderboardEntry): { role: string; model: string }[] {
  return roleLinesOf(entry.setup);
}

/** A setup's roles as the leaderboard words them; any `setup_of`-shaped object (a claim's setup too). */
export function roleLinesOf(setup: { roles?: unknown }): { role: string; model: string }[] {
  const roles = (setup.roles ?? {}) as Record<string, RoleSpec | string>;
  return Object.entries(roles).map(([role, spec]) => {
    if (typeof spec === "string") return { role, model: spec };
    const notes = [spec.reasoning_effort === "none" ? "no thinking" : spec.reasoning_effort ? `${spec.reasoning_effort} reasoning` : "",
      spec.tool_mode === "json" ? "json tools" : ""].filter(Boolean);
    return { role, model: `${spec.model ?? "?"}${notes.length ? ` (${notes.join(", ")})` : ""}` };
  });
}

export function setupPolicy(entry: LeaderboardEntry): string {
  return policyOf(entry.setup);
}

/** A setup's control policy in words. */
export function policyOf(setup: { decisions?: unknown }): string {
  const d = setup.decisions as { policy?: string; control?: string; ollaya_model?: string; jev_model?: string } | null | undefined;
  if (!d) return "the agent decides";
  const who = d.policy === "ollaya" ? `ollaya ${d.ollaya_model ?? ""}` : d.policy === "jev" ? `jev ${d.jev_model ?? ""}` : d.policy;
  return `${who} · ${d.control ?? "policy"}`;
}

/** Models an entry uses (for the model filter). */
export const modelsOf = (entry: LeaderboardEntry) => roleLines(entry).map((l) => l.model.replace(/ \(.*\)$/, ""));

export interface ScenarioSummary {
  scenario: string;
  version: string;
  leader: LeaderboardEntry;
  setups: number;
  runs: number;
  trials: number;
  legacy: boolean;
}

/** One card per scenario board: the leader and how much evidence there is. No cross-scenario ranking: setups
 *  differ per scenario (parameters, workflows), so an average across scenarios would compare unlike things. */
export function scenarioSummaries(boards: Leaderboard[]): ScenarioSummary[] {
  return boards.filter((b) => b.entries.length).map((b) => ({
    scenario: b.scenario, version: b.scenario_version, leader: b.entries[0]!, setups: b.entries.length,
    runs: new Set(b.entries.flatMap((e) => e.runs)).size, trials: b.entries.reduce((n, e) => n + e.trials, 0),
    legacy: b.scenario_version === "legacy",
  }));
}
