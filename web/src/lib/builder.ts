// Experiment builder logic: which roles the selected scenarios need, which models may fill them,
// and turning the form state into an ExperimentConfig (the same YAML the CLI runs).
import { stringify } from "yaml";

import type { CatalogItem } from "./backend";
import { applyOverride, isOverride, modelFor } from "./presets";
import type { ModelPreset, DecisionConfig, ExperimentConfig, ScenarioManifest } from "./contracts";

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
  /** scenario -> role -> model ref: per-scenario (per-step) bindings that override `roles`. A thinking override
   *  ("#reasoning=low") keeps the inherited model; toExperiment resolves it to a concrete reference. */
  scenarioRoles: Record<string, Record<string, string>>;
  /** control policy for scenarios that support one; null = the agent decides everything */
  decisions: DecisionConfig | null;
  /** model preset: roles not bound explicitly run on its model for their kind; "" = none */
  preset?: string;
  /** the user typed the name; otherwise it follows the models (suggestName) */
  named?: boolean;
}

export const POLICIES: { value: NonNullable<DecisionConfig["policy"]>; label: string }[] = [
  { value: "llm", label: "LLM (structured output)" },
  { value: "rules", label: "Rules" },
  { value: "cascade", label: "Cascade (rules → primary → fallback)" },
  { value: "jev", label: "Jev (TypeSafe, hosted)" },
  { value: "ollaya", label: "Ollaya (local decision model, e.g. winnow)" },
];

export const CONTROLS: { value: NonNullable<DecisionConfig["control"]>; label: string }[] = [
  { value: "policy", label: "policy decides next action, completion and approvals" },
  { value: "gate", label: "agent loop; policy gates risky actions" },
  { value: "review", label: "agent loop; policy reviews the trace" },
];

export const SERVICES = ["jev", "ollaya"] as const;
export type Service = (typeof SERVICES)[number];
export const SERVICE_LABELS: Record<Service, string> = { jev: "Jev", ollaya: "Ollaya" };

/** Decision services (Jev, Ollaya) a control-policy config calls. */
export function servicesUsed(decisions: DecisionConfig | null): Service[] {
  if (!decisions) return [];
  const stages = decisions.policy === "cascade" ? [decisions.primary ?? "llm", decisions.fallback] : [decisions.policy];
  return SERVICES.filter((s) => stages.includes(s));
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
  budgetMode: "best_effort" | "strict";
  /** task split for scenarios that define one (dev for tuning thresholds, test for reporting) */
  split: "all" | "dev" | "test";
  /** replacement study instead of hand-built configurations */
  study?: StudyDraft | null;
}

export interface StudyDraft {
  baseline: string;
  /** model references, or "ollaya:<model>" / "jev:<model>" decision models */
  candidates: string[];
  /** roles to swap; empty = every non-decision role of the selected scenarios */
  roles: string[];
  decisionControl: "gate" | "policy" | "review";
}

const SERVICE_PREFIXES = ["ollaya:", "jev:"];
const shortRef = (ref: string) => {
  const [base = "", settings = ""] = ref.split("#", 2);
  const name = base.includes(":") ? base.slice(base.indexOf(":") + 1) : base;
  const notes = settings.split(",").filter(Boolean).map((s) => (s === "reasoning=none" ? "no thinking" : s.replace("reasoning=", "reasoning ")));
  return notes.length ? `${name} (${notes.join(", ")})` : name;
};

/** The configurations a study will run (mirrors runner/study.py expand), for the preview and the estimate. */
export function studyConfigs(
  study: StudyDraft, manifests: ScenarioManifest[], profile: ModelPreset | undefined,
  canDo: (candidate: string, needs: string[]) => boolean = () => true,
): { name: string; scenarios: string[] }[] {
  const out = [{ name: "baseline", scenarios: manifests.map((m) => m.id) }];
  const roles = study.roles.length ? study.roles
    : [...new Set(manifests.flatMap((m) => m.roles.filter((r) => r.kind !== "decision").map((r) => r.name)))].sort();
  for (const candidate of study.candidates.filter(Boolean)) {
    if (SERVICE_PREFIXES.some((p) => candidate.startsWith(p))) {
      const controlled = manifests.filter((m) => m.supports_decisions).map((m) => m.id);
      if (controlled.length) out.push({ name: `decisions→${candidate.split(":").slice(1).join(":")}`, scenarios: controlled });
      continue;
    }
    for (const role of roles) {
      const scenarios = manifests.filter((m) => m.roles.some((r) =>
        r.name === role && modelFor(profile, r.kind ?? "text") !== candidate && canDo(candidate, r.needs ?? []))).map((m) => m.id);
      if (scenarios.length) out.push({ name: `${role}→${shortRef(candidate)}`, scenarios: scenarios.sort() });
    }
  }
  return out;
}

export function emptyConfig(index: number): ConfigDraft {
  return { name: `config-${index + 1}`, roles: { [DEFAULT_ROLE]: "" }, scenarioParams: {}, scenarioRoles: {}, decisions: null };
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

/** "ollama:qwen3.8:27b-mlx" -> "qwen3.8-27b-mlx"; "…#reasoning=none" adds "-nothink", other efforts "-low" etc. */
export function shortModel(ref: string): string {
  const [base = "", settings = ""] = ref.split("#", 2);
  const name = (base.includes(":") ? base.slice(base.indexOf(":") + 1) : base).replace(/[:/]+/g, "-");
  const reasoning = settings.split(",").find((s) => s.startsWith("reasoning="))?.slice("reasoning=".length);
  return reasoning === "none" ? `${name}-nothink` : reasoning ? `${name}-${reasoning}` : name;
}

/** A name that says what runs: the preset or default model, then every step set explicitly, then the control
 *  policy. "local-small", "qwen3.8-27b-mlx", "local-small+critic-gpt-5-mini", "qwen3-14b+ollaya". */
export function suggestName(config: ConfigDraft, profiles: Record<string, ModelPreset>, scenarios?: string[]): string {
  const pinned = new Map<string, string>();
  for (const [role, ref] of Object.entries(config.roles)) if (ref && role !== DEFAULT_ROLE) pinned.set(role, ref);
  for (const [scenario, roles] of Object.entries(config.scenarioRoles ?? {})) {
    if (scenarios && !scenarios.includes(scenario)) continue;
    for (const [role, ref] of Object.entries(roles)) if (ref) pinned.set(role, ref);
  }
  const preset = knownPreset(config, profiles);
  const base = preset || (config.roles[DEFAULT_ROLE] ? shortModel(config.roles[DEFAULT_ROLE]) : "");
  const models = [...new Set(pinned.values())];
  // A thinking override names only the thinking ("critic-low"): the model is the inherited one.
  const part = (role: string, ref: string) => (isOverride(ref) ? `${role}${shortModel(ref)}` : `${role}-${shortModel(ref)}`);
  const parts = !base && models.length === 1 && !isOverride(models[0]!) ? [shortModel(models[0]!)] // every step on the same model
    : [base, ...[...pinned].sort(([a], [b]) => a.localeCompare(b)).map(([role, ref]) => part(role, ref))];
  if (config.decisions?.policy) parts.push(config.decisions.policy);
  return parts.filter(Boolean).join("+").slice(0, 80) || "my-setup";
}

/** The config's preset if this page knows it, else "" (then the config runs on its own models). */
export function knownPreset(config: ConfigDraft, profiles: Record<string, ModelPreset>): string {
  return config.preset && profiles[config.preset] ? config.preset : "";
}

export function validate(
  state: BuilderState, manifests: ScenarioManifest[], runtimeHasSandbox: boolean,
  serviceStatus: Partial<Record<Service, string>> = {}, profiles: Record<string, ModelPreset> = {},
): string[] {
  const errors: string[] = [];
  if (!state.name.trim()) errors.push("Give the experiment a name.");
  if (state.scenarios.length === 0) errors.push("Select at least one scenario.");
  if (state.configs.length === 0) errors.push("Add at least one model configuration.");
  const names = state.configs.map((c) => c.name.trim());
  if (new Set(names).size !== names.length) errors.push("Configuration names must be unique.");
  const slots = roleSlots(manifests, state.scenarios);
  for (const config of state.configs) {
    for (const manifest of manifests.filter((m) => state.scenarios.includes(m.id))) {
      for (const [role, ref] of Object.entries(config.scenarioRoles[manifest.id] ?? {})) {
        if (isOverride(ref) && !stepModel(config, manifest, role, profiles)) {
          errors.push(`${config.name}: "${role}" in ${manifest.id} changes the thinking of a model it does not have yet; choose a model.`);
        }
      }
    }
    if (knownPreset(config, profiles)) continue; // a preset binds every role that is not set explicitly
    for (const manifest of manifests.filter((m) => state.scenarios.includes(m.id))) {
      for (const role of manifest.roles.filter((r) => !r.fallback)) {
        if (!boundModel(config, manifest.id, role.name)) {
          errors.push(`${config.name}: choose a model for "${role.name}" in ${manifest.id} (or a default model).`);
        }
      }
    }
  }
  void slots;
  if (!runtimeHasSandbox) {
    const needSandbox = manifests.filter((m) => state.scenarios.includes(m.id) && (m.requires ?? []).includes("sandbox"));
    if (needSandbox.length) errors.push(`Code execution is unavailable for ${needSandbox.map((m) => m.id).join(", ")}. Start Docker and run make sandbox-image, or restart with --sandbox unsafe-process (not isolated).`);
  }
  if (state.arena && !state.judge) errors.push("Arena battles need a judge model.");
  const controllable = controllableScenarios(state, manifests);
  for (const config of state.configs.filter((c) => c.decisions)) {
    if (!controllable.length) errors.push(`${config.name}: none of the selected scenarios supports a control policy.`);
    for (const service of servicesUsed(config.decisions)) {
      const status = serviceStatus[service] ?? "available";
      if (status !== "available") errors.push(`${config.name}: ${SERVICE_LABELS[service]} is unavailable (${status}).`);
    }
  }
  return errors;
}

/** The model a role is bound to in one scenario: per-scenario binding, config-wide role, the preset (by the role's
 *  kind), then the default model. Mirrors ExperimentRunner._bind; fallback roles are left to stepModel. */
export function boundModel(
  config: ConfigDraft, scenario: string, role: string, kind = "text", profiles: Record<string, ModelPreset> = {},
): string {
  const inherited = config.roles[role] || (knownPreset(config, profiles) ? modelFor(profiles[config.preset!], kind) : "")
    || config.roles[DEFAULT_ROLE] || "";
  const own = config.scenarioRoles[scenario]?.[role];
  return own ? applyOverride(own, inherited) : inherited;
}

type RolesOf = Pick<ScenarioManifest, "id" | "roles">;

/** The concrete model a step runs on in one scenario, as the runner binds it: its own binding (a thinking override
 *  applies to what it would inherit), else what it inherits. */
export function stepModel(
  config: ConfigDraft, manifest: RolesOf, role: string, profiles: Record<string, ModelPreset> = {}, seen = new Set<string>(),
): string {
  const inherited = inheritedModel(config, manifest, role, profiles, seen);
  const own = config.scenarioRoles[manifest.id]?.[role];
  return own ? applyOverride(own, inherited) : inherited;
}

/** What a step runs on without a binding of its own in this scenario: a config-wide binding, the preset's model for
 *  the step's kind, the fallback step's model (critic = generator), then the default model. */
export function inheritedModel(
  config: ConfigDraft, manifest: RolesOf, role: string, profiles: Record<string, ModelPreset> = {}, seen = new Set<string>(),
): string {
  if (config.roles[role]) return config.roles[role];
  const requirement = manifest.roles.find((r) => r.name === role);
  const preset = knownPreset(config, profiles);
  if (preset) return modelFor(profiles[preset], requirement?.kind ?? "text");
  const fallback = requirement?.fallback;
  if (fallback && !seen.has(fallback)) return stepModel(config, manifest, fallback, profiles, new Set([...seen, role]));
  return config.roles[DEFAULT_ROLE] || "";
}

/** Roles a control policy calls (mirrors DecisionConfig.llm_roles). */
export function llmRoles(decisions: DecisionConfig | null): string[] {
  if (!decisions) return [];
  if (decisions.policy === "llm") return ["decider"];
  if (decisions.policy !== "cascade") return [];
  return [...((decisions.primary ?? "llm") === "llm" ? ["decider"] : []), ...(decisions.fallback === "llm" ? ["escalation"] : [])];
}

export function policyLabel(decisions: DecisionConfig | null): string {
  if (!decisions) return "";
  const stage = (s: string | null | undefined) => (s === "ollaya" ? `ollaya ${decisions.ollaya_model ?? ""}`.trim() : s ?? "");
  if (decisions.policy === "cascade") {
    return ["cascade:", decisions.hard_rules === false ? "" : "rules →", stage(decisions.primary ?? "llm"),
      decisions.fallback ? `→ ${stage(decisions.fallback)}` : ""].filter(Boolean).join(" ");
  }
  return stage(decisions.policy);
}

export function controllableScenarios(state: BuilderState, manifests: ScenarioManifest[]): string[] {
  return manifests.filter((m) => state.scenarios.includes(m.id) && m.supports_decisions).map((m) => m.id);
}

export function toExperiment(
  state: BuilderState, manifests: ScenarioManifest[] = [], profiles: Record<string, ModelPreset> = {},
): ExperimentConfig {
  if (state.study) return studyExperiment(state, state.study, profiles);
  const controllable = controllableScenarios(state, manifests);
  const experiment: ExperimentConfig = {
    name: state.name.trim(),
    scenarios: [...state.scenarios],
    repeats: state.repeats,
    configs: state.configs.map((config) => {
      // What runs is what the page shows: a preset the page does not know (not loaded, removed, not usable in this
      // runtime) is dropped, and with a known preset the hidden default model is, since the preset outranks it.
      const preset = knownPreset(config, profiles);
      const roles = Object.fromEntries(Object.entries(config.roles).filter(([role, ref]) => ref && !(preset && role === DEFAULT_ROLE)));
      const scenarioParams = Object.fromEntries(
        Object.entries(config.scenarioParams).filter(([id, params]) => state.scenarios.includes(id) && Object.keys(params).length),
      );
      // Thinking overrides become the concrete model they stand for: the engine and the recorded setup see what ran.
      const concrete = (id: string, role: string, ref: string) => (isOverride(ref)
        ? stepModel(config, manifests.find((m) => m.id === id) ?? { id, roles: [] }, role, profiles) : ref);
      const scenarioRoles = Object.fromEntries(
        Object.entries(config.scenarioRoles ?? {})
          .filter(([id]) => state.scenarios.includes(id))
          .map(([id, roles]) => [id, Object.fromEntries(Object.entries(roles)
            .map(([role, ref]) => [role, ref && concrete(id, role, ref)]).filter(([, ref]) => ref))])
          .filter(([, roles]) => Object.keys(roles as object).length),
      ) as Record<string, Record<string, string>>;
      return {
        name: config.name.trim(),
        roles,
        ...(Object.keys(scenarioParams).length ? { scenario_params: scenarioParams } : {}),
        ...(Object.keys(scenarioRoles).length ? { scenario_roles: scenarioRoles } : {}),
        ...(preset ? { preset } : {}),
        // A control policy applies only where a scenario supports one, so such a config runs only those scenarios.
        ...(config.decisions ? { decisions: { ...config.decisions }, scenarios: controllable } : {}),
      };
    }),
  };
  if (state.limit) experiment.limit = state.limit;
  if (state.judge) experiment.judge = state.judge;
  if (state.arena) experiment.arena = { enabled: true };
  if (state.maxCostUsd) experiment.max_cost_usd = state.maxCostUsd;
  if (state.maxCostUsd && state.budgetMode === "strict") experiment.budget_mode = "strict";
  if (state.split !== "all") experiment.split = state.split;
  // Profiles travel with the experiment, so edited ones work in every runtime and the YAML is self-contained.
  const used = [...new Set(state.configs.map((c) => knownPreset(c, profiles)).filter(Boolean))];
  if (used.length) experiment.presets = Object.fromEntries(used.map((b) => [b, profiles[b]!]));
  return experiment;
}

function studyExperiment(state: BuilderState, study: StudyDraft, profiles: Record<string, ModelPreset>): ExperimentConfig {
  const experiment: ExperimentConfig = {
    name: state.name.trim(),
    scenarios: [...state.scenarios],
    repeats: state.repeats,
    study: {
      baseline: study.baseline,
      candidates: study.candidates.filter(Boolean) as [string, ...string[]], // validateStudy requires one
      ...(study.roles.length ? { roles: [...study.roles] } : {}),
      decision_control: study.decisionControl,
    },
  };
  if (state.limit) experiment.limit = state.limit;
  if (state.maxCostUsd) experiment.max_cost_usd = state.maxCostUsd;
  if (state.maxCostUsd && state.budgetMode === "strict") experiment.budget_mode = "strict";
  if (state.split !== "all") experiment.split = state.split;
  if (profiles[study.baseline]) experiment.presets = { [study.baseline]: profiles[study.baseline]! };
  return experiment;
}

export function validateStudy(state: BuilderState, study: StudyDraft): string[] {
  const errors: string[] = [];
  if (!state.name.trim()) errors.push("Give the study a name.");
  if (!state.scenarios.length) errors.push("Select at least one scenario.");
  if (!study.baseline) errors.push("Choose the baseline preset.");
  if (!study.candidates.some(Boolean)) errors.push("Add at least one candidate model.");
  return errors;
}

export function toYaml(experiment: ExperimentConfig): string {
  return `# Run with: uv run arena run <this file>\n${stringify(experiment)}`;
}
