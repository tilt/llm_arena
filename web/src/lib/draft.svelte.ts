// The experiment being built, shared between the Experiments view and scenario pages ("Add to experiment").
import { starterConfig, type BuilderState, type ConfigDraft } from "./builder";
import { activePreset } from "./presets";

export const draft = $state<BuilderState>({
  name: "my-experiment", scenarios: [], configs: [starterConfig(activePreset())], repeats: 1, limit: 3, judge: "", arena: false,
  maxCostUsd: 1, budgetMode: "best_effort", split: "all", suite: "", variants: [],
});

/** Whether a bundle is still a starter: the app gave it its preset (autoPreset) and the user chose nothing in it, not
 *  even another preset (when unsure, it counts as chosen and stays). */
export function isStarter(config: ConfigDraft): boolean {
  return config.autoPreset !== undefined && (config.preset ?? "") === config.autoPreset && !config.named
    && !Object.values(config.roles).some(Boolean)
    && !Object.values(config.kinds ?? {}).some(Boolean) && !Object.keys(config.scenarioRoles).length
    && !Object.keys(config.scenarioParams).length && !config.decisions;
}

/** Untouched starters start from `start`, the preset new setups start from (one that runs here, or none). Every other
 *  setup keeps its preset, even one that is unavailable for now: the user chose it. */
export function adoptStartPreset(configs: ConfigDraft[], start: string): void {
  for (const config of configs.filter((c) => isStarter(c) && (c.preset ?? "") !== start)) {
    config.preset = start;
    config.autoPreset = start;
  }
}

/** Add a scenario with one configured setup; replaces the untouched starter config. The added setup is the user's. */
export function addToDraft(scenario: string, config: ConfigDraft): void {
  if (!draft.scenarios.includes(scenario)) draft.scenarios = [...draft.scenarios, scenario];
  const untouched = draft.configs.length === 1 && isStarter(draft.configs[0]!);
  const taken = new Set(draft.configs.map((c) => c.name));
  let name = config.name;
  for (let i = 2; taken.has(name) && !untouched; i++) name = `${config.name}-${i}`;
  const added = { ...config, name, autoPreset: undefined };
  draft.configs = untouched ? [added] : [...draft.configs, added];
}

/** A setup handed from the leaderboard to a scenario page ("Use this setup"); the page takes it once. */
export const handoff = $state({ setup: null as { scenario: string; config: ConfigDraft; note: string } | null });
