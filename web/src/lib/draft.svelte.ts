// The experiment being built, shared between the Experiments view and scenario pages ("Add to experiment").
import { activePreset } from "./presets";
import { emptyConfig, type BuilderState, type ConfigDraft } from "./builder";

export const draft = $state<BuilderState>({
  name: "my-experiment", scenarios: [], configs: [{ ...emptyConfig(0), preset: activePreset() }], repeats: 1, limit: 3, judge: "", arena: false,
  maxCostUsd: 1, budgetMode: "best_effort", split: "all", suite: "", variants: [],
});

/** Whether a bundle is still the starter: nothing the user chose in it (when unsure, it counts as chosen and stays). */
export function isStarter(config: ConfigDraft): boolean {
  return !config.named && (config.preset ?? "") === activePreset() && !Object.values(config.roles).some(Boolean)
    && !Object.values(config.kinds ?? {}).some(Boolean) && !Object.keys(config.scenarioRoles).length
    && !Object.keys(config.scenarioParams).length && !config.decisions;
}

/** Add a scenario with one configured setup; replaces the untouched starter config. */
export function addToDraft(scenario: string, config: ConfigDraft): void {
  if (!draft.scenarios.includes(scenario)) draft.scenarios = [...draft.scenarios, scenario];
  const untouched = draft.configs.length === 1 && isStarter(draft.configs[0]!);
  const taken = new Set(draft.configs.map((c) => c.name));
  let name = config.name;
  for (let i = 2; taken.has(name) && !untouched; i++) name = `${config.name}-${i}`;
  draft.configs = untouched ? [{ ...config, name }] : [...draft.configs, { ...config, name }];
}

/** A setup handed from the leaderboard to a scenario page ("Use this setup"); the page takes it once. */
export const handoff = $state({ setup: null as { scenario: string; config: ConfigDraft; note: string } | null });
