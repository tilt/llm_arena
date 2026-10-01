// The experiment being built, shared between the Build view and scenario pages ("Add to experiment").
import { activePreset } from "./presets";
import { emptyConfig, type BuilderState, type ConfigDraft } from "./builder";

export const draft = $state<BuilderState>({
  name: "my-experiment", scenarios: [], configs: [{ ...emptyConfig(0), preset: activePreset() }], repeats: 1, limit: 3, judge: "", arena: false,
  maxCostUsd: 1, budgetMode: "best_effort", split: "all",
});

/** Add a scenario with one configured setup; replaces the untouched starter config. */
export function addToDraft(scenario: string, config: ConfigDraft): void {
  if (!draft.scenarios.includes(scenario)) draft.scenarios = [...draft.scenarios, scenario];
  const first = draft.configs[0]!;
  const untouched = draft.configs.length === 1 && !Object.values(first.roles).some(Boolean) && !Object.keys(first.scenarioRoles).length;
  const taken = new Set(draft.configs.map((c) => c.name));
  let name = config.name;
  for (let i = 2; taken.has(name) && !untouched; i++) name = `${config.name}-${i}`;
  draft.configs = untouched ? [{ ...config, name }] : [...draft.configs, { ...config, name }];
}

/** A setup handed from the leaderboard to a scenario page ("Use this setup"); the page takes it once. */
export const handoff = $state({ setup: null as { scenario: string; config: ConfigDraft; note: string } | null });
