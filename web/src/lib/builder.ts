// Experiment builder logic: which roles the selected scenarios need, which models may fill them,
// and turning the form state into an ExperimentConfig (the same YAML the CLI runs).
import { stringify } from "yaml";

import type { CatalogItem } from "./backend";
import type { ExperimentConfig, ScenarioManifest } from "./contracts";

export const DEFAULT_ROLE = "*";

/** Wiki pages shared by every scenario; scenario cards show only their pattern's own pages. */
export const EVALUATION_PAGES = new Set(["Agent evaluation", "Evaluation harnesses", "LLM-as-judge"]);

export interface RoleSlot {
  name: string;
  needs: string[];
  /** scenarios using this role */
  scenarios: string[];
  /** true when every scenario has a fallback for it (it may stay unbound) */
  optional: boolean;
  description: string;
}

export interface ConfigDraft {
  name: string;
  /** role -> model ref; DEFAULT_ROLE binds every role that is not set explicitly */
  roles: Record<string, string>;
  scenarioParams: Record<string, Record<string, unknown>>;
}

export interface BuilderState {
  name: string;
  scenarios: string[];
  configs: ConfigDraft[];
  repeats: number;
  limit: number | null;
  /** judge model ref; "" = no judge */
  judge: string;
  arena: boolean;
  maxCostUsd: number | null;
}

export function emptyConfig(index: number): ConfigDraft {
  return { name: `config-${index + 1}`, roles: { [DEFAULT_ROLE]: "" }, scenarioParams: {} };
}

/** Union of roles over the selected scenarios; capability needs are merged. */
export function roleSlots(manifests: ScenarioManifest[], selected: string[]): RoleSlot[] {
  const slots = new Map<string, RoleSlot>();
  for (const manifest of manifests.filter((m) => selected.includes(m.id))) {
    for (const role of manifest.roles) {
      const slot = slots.get(role.name) ?? { name: role.name, needs: [], scenarios: [], optional: true, description: role.description };
      slot.needs = [...new Set([...slot.needs, ...(role.needs ?? [])])].sort();
      slot.scenarios.push(manifest.id);
      slot.optional = slot.optional && Boolean(role.fallback);
      slots.set(role.name, slot);
    }
  }
  return [...slots.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function eligibleModels(catalog: CatalogItem[], needs: string[]): CatalogItem[] {
  return catalog.filter((item) => needs.every((need) => Boolean((item.spec.capabilities as Record<string, unknown> | undefined)?.[need])));
}

/** Needs of the default ("*") role: every non-optional role it would fill that is not bound explicitly. */
export function defaultRoleNeeds(slots: RoleSlot[], config: ConfigDraft): string[] {
  return [...new Set(slots.filter((s) => !s.optional && !config.roles[s.name]).flatMap((s) => s.needs))].sort();
}

export function validate(state: BuilderState, manifests: ScenarioManifest[], runtimeHasSandbox: boolean): string[] {
  const errors: string[] = [];
  if (!state.name.trim()) errors.push("Give the experiment a name.");
  if (state.scenarios.length === 0) errors.push("Select at least one scenario.");
  if (state.configs.length === 0) errors.push("Add at least one model configuration.");
  const names = state.configs.map((c) => c.name.trim());
  if (new Set(names).size !== names.length) errors.push("Configuration names must be unique.");
  const slots = roleSlots(manifests, state.scenarios);
  for (const config of state.configs) {
    for (const slot of slots.filter((s) => !s.optional)) {
      if (!config.roles[slot.name] && !config.roles[DEFAULT_ROLE]) {
        errors.push(`${config.name}: choose a model for "${slot.name}" (or a default model).`);
      }
    }
  }
  if (!runtimeHasSandbox) {
    const needSandbox = manifests.filter((m) => state.scenarios.includes(m.id) && (m.requires ?? []).includes("sandbox"));
    if (needSandbox.length) errors.push(`This runtime cannot execute code: remove ${needSandbox.map((m) => m.id).join(", ")}.`);
  }
  if (state.arena && !state.judge) errors.push("Arena battles need a judge model.");
  return errors;
}

export function toExperiment(state: BuilderState): ExperimentConfig {
  const experiment: ExperimentConfig = {
    name: state.name.trim(),
    scenarios: [...state.scenarios],
    repeats: state.repeats,
    configs: state.configs.map((config) => {
      const roles = Object.fromEntries(Object.entries(config.roles).filter(([, ref]) => ref));
      const scenarioParams = Object.fromEntries(
        Object.entries(config.scenarioParams).filter(([id, params]) => state.scenarios.includes(id) && Object.keys(params).length),
      );
      return { name: config.name.trim(), roles, ...(Object.keys(scenarioParams).length ? { scenario_params: scenarioParams } : {}) };
    }),
  };
  if (state.limit) experiment.limit = state.limit;
  if (state.judge) experiment.judge = state.judge;
  if (state.arena) experiment.arena = { enabled: true };
  if (state.maxCostUsd) experiment.max_cost_usd = state.maxCostUsd;
  return experiment;
}

export function toYaml(experiment: ExperimentConfig): string {
  return `# Run with: uv run arena run <this file>\n${stringify(experiment)}`;
}
