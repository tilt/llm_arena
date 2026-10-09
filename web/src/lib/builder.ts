// Experiment builder logic: which roles the selected scenarios need, which models may fill them,
// and turning the form state into an ExperimentConfig (the same YAML the CLI runs).
import { stringify } from "yaml";

import type { CatalogItem } from "./backend";
import { KINDS, applyOverride, isOverride, modelFor, splitRef } from "./presets";
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
  /** step kind -> model: this bundle's own model for a kind, over the preset's (or the one model's) */
  kinds?: Record<string, string>;
  /** the experiment's baseline: the report shows every other bundle's effect against it (per variant) */
  baseline?: boolean;
  /** runs only in these scenarios (a swap runs where it changes its step); unset = every selected scenario */
  only?: string[];
  /** the one step this bundle changes against the bundle it was made from (swapSetups, `from` = that bundle's id):
   *  the report compares it with that bundle, whichever is marked as the baseline, and labels the effect by step */
  swap?: { role: string; candidate: string; from: string };
  /** stable identity (names change), so swaps can name the bundle they were made from */
  id?: string;
}

export const configId = (): string => crypto.randomUUID();

/** One way of running the scenarios (a method variant): parameters and a control policy. Every model bundle runs
 *  every variant; no variants means one plain run per bundle. */
export interface VariantDraft {
  name: string;
  /** applied to every selected scenario that has the parameter */
  params: Record<string, unknown>;
  decisions: DecisionConfig | null;
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
  /** the suite that filled in what to run ("" = the user's own choice) */
  suite?: string;
  /** method variants; every bundle runs each one */
  variants?: VariantDraft[];
}

/** Bundles that each swap one step of the baseline to a candidate model (a replacement study, as bundles): one per
 *  (role, candidate), running only in the scenarios where the swap changes something. A swap the candidate cannot do
 *  (a capability the step needs) or that changes nothing (the baseline already runs it) is skipped, with the reason. */
export function swapSetups(
  base: ConfigDraft, candidates: string[], roles: string[], manifests: ScenarioManifest[],
  profiles: Record<string, ModelPreset> = {}, catalog: CatalogItem[] = [],
): { setups: ConfigDraft[]; skipped: { role: string; candidate: string; scenario: string; why: string }[] } {
  const setups: ConfigDraft[] = [];
  const skipped: { role: string; candidate: string; scenario: string; why: string }[] = [];
  for (const candidate of candidates.filter(Boolean)) {
    for (const role of roles) {
      const swapped: string[] = [];
      for (const manifest of manifests.filter((m) => !base.only || base.only.includes(m.id))) {
        const requirement = manifest.roles.find((r) => r.name === role);
        if (!requirement) continue;
        const skip = (why: string) => skipped.push({ role, candidate, scenario: manifest.title, why });
        const missing = lacking(catalog, candidate, requirement.needs ?? []);
        if (stepModel(base, manifest, role, profiles) === candidate) skip("the baseline already runs it");
        else if (missing.length) skip(`lacks ${missing.join(", ")}`);
        else swapped.push(manifest.id);
      }
      if (!swapped.length) continue;
      const copy = JSON.parse(JSON.stringify(base)) as ConfigDraft; // a bundle of its own, not sharing the baseline's
      copy.id = configId();
      for (const id of swapped) {
        const manifest = manifests.find((m) => m.id === id)!;
        const before = Object.fromEntries(manifest.roles.map((r) => [r.name, stepModel(base, manifest, r.name, profiles)]));
        copy.scenarioRoles[id] = { ...(copy.scenarioRoles[id] ?? {}), [role]: candidate };
        // Steps that follow the swapped one (a critic falling back to the generator) keep the baseline's model, so
        // exactly one step changes.
        for (const other of manifest.roles.filter((r) => r.name !== role)) {
          if (stepModel(copy, manifest, other.name, profiles) !== before[other.name]) copy.scenarioRoles[id]![other.name] = before[other.name]!;
        }
      }
      setups.push({
        ...copy, name: `${role}→${shortModel(candidate)}`, named: true, baseline: false, only: swapped,
        swap: { role, candidate, from: base.id ?? "" },
      });
    }
  }
  return { setups, skipped };
}

/** Why a swap no longer measures its one step against the bundle it was made from: that bundle was removed, or
 *  it (or the swap) changed since, so they differ in more than the swapped step. "" = still a clean swap. */
export function swapProblem(
  bundle: ConfigDraft, configs: ConfigDraft[], manifests: ScenarioManifest[], profiles: Record<string, ModelPreset> = {},
): string {
  if (!bundle.swap) return "";
  const { role, candidate, from } = bundle.swap;
  const origin = configs.find((c) => c !== bundle && c.id && c.id === from);
  if (!origin) return "the setup it swaps a step of was removed";
  const changed = `differs from ${origin.name.trim()} in more than the ${role} now`;
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  if (!same(bundle.decisions, origin.decisions)) return changed;
  for (const manifest of manifests.filter((m) => !bundle.only || bundle.only.includes(m.id))) {
    if (!same(bundle.scenarioParams[manifest.id], origin.scenarioParams[manifest.id])) return changed;
    for (const r of manifest.roles) {
      const theirs = stepModel(origin, manifest, r.name, profiles);
      const ours = stepModel(bundle, manifest, r.name, profiles);
      // The swapped step runs the candidate (or, where the candidate could not do it, still the original model).
      if (ours !== theirs && !(r.name === role && ours === candidate)) return changed;
    }
  }
  return "";
}

/** The selected scenarios a bundle runs: those it is limited to (only), and with a control policy only those that
 *  support one. */
export function runsIn(bundle: ConfigDraft, state: BuilderState, manifests: ScenarioManifest[]): string[] {
  const controllable = new Set(controllableScenarios(state, manifests));
  return state.scenarios.filter((id) => (!bundle.only || bundle.only.includes(id)) && (!bundle.decisions || controllable.has(id)));
}

export function emptyConfig(index: number): ConfigDraft {
  return { name: `config-${index + 1}`, roles: { [DEFAULT_ROLE]: "" }, scenarioParams: {}, scenarioRoles: {}, decisions: null };
}

/** A setup that runs every step on one model (named after it until the user types a name). */
export function configForModel(ref: string): ConfigDraft {
  return { ...emptyConfig(0), name: shortModel(ref), roles: { [DEFAULT_ROLE]: ref }, preset: "" };
}

/** A setup that gives each step its preset's model for the step's kind. */
export function configForPreset(preset: string): ConfigDraft {
  return { ...emptyConfig(0), name: preset, preset };
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
  for (const [kind, ref] of Object.entries(config.kinds ?? {})) if (ref) pinned.set(kind, ref);
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

/** The models a bundle runs per step kind: its own per kind (a thinking override changes only the thinking of the
 *  inherited one), else its preset's, else its one model. */
export function bundleModels(config: ConfigDraft, profiles: Record<string, ModelPreset>): Record<string, string> {
  const preset = knownPreset(config, profiles);
  return Object.fromEntries(KINDS.map(({ kind }) => {
    const inherited = preset ? modelFor(profiles[preset], kind) : config.roles[DEFAULT_ROLE] || "";
    const own = config.kinds?.[kind] || "";
    return [kind, own ? applyOverride(own, inherited) : inherited];
  }));
}

const hasKinds = (config: ConfigDraft) => Object.values(config.kinds ?? {}).some(Boolean);

/** A bundle with models of its own per kind runs as a preset of its own, defined in the experiment (the engine
 *  binds roles by kind only through presets). Its name never shadows a real preset. Other bundles stay as they are. */
export function withKinds(
  config: ConfigDraft, profiles: Record<string, ModelPreset>,
): { config: ConfigDraft; profiles: Record<string, ModelPreset> } {
  if (!hasKinds(config)) return { config, profiles };
  let name = `${config.name.trim() || "bundle"}-models`;
  for (let i = 2; profiles[name]; i++) name = `${config.name.trim() || "bundle"}-models-${i}`;
  const base = knownPreset(config, profiles);
  const label = base ? `${profiles[base]!.label}, edited` : "Models per step kind";
  const roles = Object.fromEntries(Object.entries(config.roles).filter(([role]) => role !== DEFAULT_ROLE));
  return {
    config: { ...config, preset: name, roles, kinds: {} },
    profiles: { ...profiles, [name]: { label, description: `Models of ${config.name} in this experiment`, models: bundleModels(config, profiles) } },
  };
}

/** The config's preset if this page knows it, else "" (then the config runs on its own models). */
export function knownPreset(config: ConfigDraft, profiles: Record<string, ModelPreset>): string {
  return config.preset && profiles[config.preset] ? config.preset : "";
}

/** The engine configurations a draft runs: every model bundle with every variant ("bundle/variant"), or each bundle
 *  on its own when there are no variants. A variant's control policy replaces the bundle's. */
export function expandConfigs(state: BuilderState): { bundle: ConfigDraft; variant: VariantDraft | null; name: string }[] {
  const variants = state.variants ?? [];
  if (!variants.length) return state.configs.map((bundle) => ({ bundle, variant: null, name: bundle.name.trim() }));
  return state.configs.flatMap((bundle) => variants.map((variant) => ({
    bundle: { ...bundle, decisions: variant.decisions }, variant, name: `${bundle.name.trim()}/${variant.name.trim()}`,
  })));
}

export function validate(
  state: BuilderState, manifests: ScenarioManifest[], runtimeHasSandbox: boolean,
  serviceStatus: Partial<Record<Service, string>> = {}, allProfiles: Record<string, ModelPreset> = {}, catalog: CatalogItem[] = [],
): string[] {
  const errors: string[] = [];
  if (!state.name.trim()) errors.push("Give the experiment a name.");
  if (state.scenarios.length === 0) errors.push("Select at least one scenario.");
  if (state.configs.length === 0) errors.push("Add at least one setup.");
  const bundles = state.configs.map((c) => c.name.trim());
  if (new Set(bundles).size !== bundles.length) errors.push("Setup names must be unique.");
  const variants = (state.variants ?? []).map((v) => v.name.trim());
  if (variants.some((v) => !v)) errors.push("Give every variant a name.");
  if (new Set(variants).size !== variants.length) errors.push("Variant names must be unique.");
  const selected = manifests.filter((m) => state.scenarios.includes(m.id));
  for (const bundle of state.configs) {
    const { config, profiles } = withKinds(bundle, allProfiles);
    for (const manifest of selected) {
      for (const role of manifest.roles) {
        if (isOverride(config.roles[role.name] || "") && !inheritedModel(config, manifest, role.name, profiles)) {
          errors.push(`${config.name}: "${role.name}" changes the thinking of a model it does not have yet; choose a model or preset.`);
        }
      }
      for (const [role, ref] of Object.entries(config.scenarioRoles[manifest.id] ?? {})) {
        if (isOverride(ref) && !stepModel(config, manifest, role, profiles)) {
          errors.push(`${config.name}: "${role}" in ${manifest.id} changes the thinking of a model it does not have yet; choose a model.`);
        }
      }
      for (const role of manifest.roles.filter((r) => !r.fallback || knownPreset(config, profiles))) {
        if (!stepModel(config, manifest, role.name, profiles)) {
          errors.push(`${config.name}: choose a model for "${role.name}" in ${manifest.id}.`);
        }
      }
    }
  }
  if (!runtimeHasSandbox) {
    const needSandbox = selected.filter((m) => (m.requires ?? []).includes("sandbox"));
    if (needSandbox.length) errors.push(`Code execution is unavailable for ${needSandbox.map((m) => m.id).join(", ")}. Start Docker and run make sandbox-image, or restart with --sandbox unsafe-process (not isolated).`);
  }
  errors.push(...missingCapabilities(state, manifests, allProfiles, catalog));
  for (const { bundle, name } of expandConfigs(state)) {
    if (state.scenarios.length && !runsIn(bundle, state, manifests).length && (bundle.only || !bundle.decisions)) {
      errors.push(`${name}: runs in none of the selected scenarios.`);
    }
  }
  if (state.configs.filter((c) => c.baseline).length > 1) errors.push("Mark only one setup as the baseline.");
  for (const bundle of state.configs) {
    const problem = swapProblem(bundle, state.configs, selected, allProfiles);
    if (problem) errors.push(`${bundle.name}: ${problem}; remove it or add the swaps again.`);
  }
  if (state.arena && !state.judge) errors.push("Arena battles need a judge model.");
  const controllable = controllableScenarios(state, manifests);
  for (const { bundle, name } of expandConfigs(state).filter(({ bundle }) => bundle.decisions)) {
    if (!controllable.length) errors.push(`${name}: none of the selected scenarios supports a control policy.`);
    for (const service of servicesUsed(bundle.decisions)) {
      const status = serviceStatus[service] ?? "available";
      if (status !== "available") errors.push(`${name}: ${SERVICE_LABELS[service]} is unavailable (${status}).`);
    }
  }
  return [...new Set(errors)];
}

/** The model a role is bound to in one scenario: per-scenario binding, config-wide role, the preset (by the role's
 *  kind), then the default model. Mirrors ExperimentRunner._bind; fallback roles are left to stepModel. */
export function boundModel(
  bundle: ConfigDraft, scenario: string, role: string, kind = "text", allProfiles: Record<string, ModelPreset> = {},
): string {
  const { config, profiles } = withKinds(bundle, allProfiles);
  const ownRole = config.roles[role] || "";
  const inherited = (ownRole && !isOverride(ownRole) ? ownRole : "") || (knownPreset(config, profiles) ? modelFor(profiles[config.preset!], kind) : "")
    || config.roles[DEFAULT_ROLE] || "";
  const withRole = ownRole && isOverride(ownRole) ? applyOverride(ownRole, inherited) : inherited;
  const own = config.scenarioRoles[scenario]?.[role];
  return own ? applyOverride(own, withRole) : withRole;
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
  bundle: ConfigDraft, manifest: RolesOf, role: string, allProfiles: Record<string, ModelPreset> = {}, seen = new Set<string>(),
): string {
  const { config, profiles } = withKinds(bundle, allProfiles);
  const ownRole = config.roles[role] || "";
  if (ownRole && !isOverride(ownRole)) return ownRole;
  const requirement = manifest.roles.find((r) => r.name === role);
  const preset = knownPreset(config, profiles);
  const inherited = preset ? modelFor(profiles[preset], requirement?.kind ?? "text")
    : requirement?.fallback && !seen.has(requirement.fallback) ? stepModel(config, manifest, requirement.fallback, profiles, new Set([...seen, role]))
      : config.roles[DEFAULT_ROLE] || "";
  return ownRole && isOverride(ownRole) ? applyOverride(ownRole, inherited) : inherited;
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
  state: BuilderState, manifests: ScenarioManifest[] = [], allProfiles: Record<string, ModelPreset> = {},
): ExperimentConfig {
  const usedPresets: Record<string, ModelPreset> = {};
  const experiment: ExperimentConfig = {
    name: state.name.trim(),
    scenarios: [...state.scenarios],
    repeats: state.repeats,
    configs: expandConfigs(state).map(({ bundle, variant, name }) => {
      // A swap is compared with the bundle it was made from; every other bundle with the baseline. Both under the same
      // variant.
      const against = bundle.swap ? state.configs.find((c) => c.id && c.id === bundle.swap!.from)
        : bundle.baseline ? undefined : state.configs.find((c) => c.baseline);
      const compareTo = against ? (variant ? `${against.name.trim()}/${variant.name.trim()}` : against.name.trim()) : "";
      const scenarios = runsIn(bundle, state, manifests);
      const { config, profiles } = withKinds(bundle, allProfiles);
      // What runs is what the page shows: a preset the page does not know (not loaded, removed, not usable in this
      // runtime) is dropped, and with a known preset the hidden default model is, since the preset outranks it.
      const preset = knownPreset(config, profiles);
      if (preset) usedPresets[preset] = profiles[preset]!;
      const roles = Object.fromEntries(Object.entries(config.roles).filter(([role, ref]) => ref && !isOverride(ref) && !(preset && role === DEFAULT_ROLE)));
      const scenarioParams = Object.fromEntries(
        Object.entries(config.scenarioParams).filter(([id, params]) => state.scenarios.includes(id) && Object.keys(params).length),
      );
      // Thinking overrides become the concrete model they stand for: the engine and the recorded setup see what ran.
      const concrete = (id: string, role: string, ref: string) => (isOverride(ref)
        ? stepModel(config, manifests.find((m) => m.id === id) ?? { id, roles: [] }, role, profiles) : ref);
      const roleOverrides = Object.fromEntries(
        manifests.filter((m) => state.scenarios.includes(m.id)).map((manifest) => {
          const roles = Object.fromEntries(manifest.roles
            .filter((role) => isOverride(config.roles[role.name] || ""))
            .map((role) => [role.name, stepModel(config, manifest, role.name, profiles)])
            .filter(([, ref]) => ref));
          return [manifest.id, roles];
        }).filter(([, roles]) => Object.keys(roles as object).length),
      ) as Record<string, Record<string, string>>;
      const scenarioRoles = Object.fromEntries(
        Object.entries(config.scenarioRoles ?? {})
          .filter(([id]) => state.scenarios.includes(id))
          .map(([id, roles]) => [id, Object.fromEntries(Object.entries(roles)
            .map(([role, ref]) => [role, ref && concrete(id, role, ref)]).filter(([, ref]) => ref))])
          .map(([id, roles]) => [id, { ...(roleOverrides[id] ?? {}), ...(roles as Record<string, string>) }])
          .filter(([, roles]) => Object.keys(roles as object).length),
      ) as Record<string, Record<string, string>>;
      for (const [id, roles] of Object.entries(roleOverrides)) if (!scenarioRoles[id]) scenarioRoles[id] = roles;
      const params = Object.fromEntries(Object.entries(variant?.params ?? {}).filter(([, value]) => value !== "" && value != null));
      return {
        name,
        roles,
        ...(Object.keys(params).length ? { params } : {}),
        ...(Object.keys(scenarioParams).length ? { scenario_params: scenarioParams } : {}),
        ...(Object.keys(scenarioRoles).length ? { scenario_roles: scenarioRoles } : {}),
        ...(preset ? { preset } : {}),
        ...(config.decisions ? { decisions: { ...config.decisions } } : {}),
        // A control policy applies only where a scenario supports one, and a swap runs only where it changes a step.
        ...(scenarios.length < state.scenarios.length ? { scenarios } : {}),
        ...(compareTo ? { compare_to: compareTo } : {}),
        ...(bundle.swap ? { study: { kind: "swap" as const, role: bundle.swap.role, candidate: bundle.swap.candidate } } : {}),
      };
    }),
  };
  if (state.limit) experiment.limit = state.limit;
  if (state.judge) experiment.judge = state.judge;
  if (state.arena) experiment.arena = { enabled: true };
  if (state.maxCostUsd) experiment.max_cost_usd = state.maxCostUsd;
  if (state.maxCostUsd && state.budgetMode === "strict") experiment.budget_mode = "strict";
  if (state.split !== "all") experiment.split = state.split;
  // Presets travel with the experiment, so edited ones (and bundles' own) work in every runtime and the YAML is
  // self-contained.
  if (Object.keys(usedPresets).length) experiment.presets = usedPresets;
  return experiment;
}

export function toYaml(experiment: ExperimentConfig): string {
  return `# Run with: uv run arena run <this file>\n${stringify(experiment)}`;
}

/** The step kinds the selected scenarios use, in KINDS order; decision steps only when a control policy calls an
 *  LLM (otherwise they never run). */
export function kindsUsed(state: BuilderState, manifests: ScenarioManifest[]): { kind: string; roles: string[]; needs: string[] }[] {
  const decides = expandConfigs(state).some(({ bundle }) => llmRoles(bundle.decisions).length);
  const roles = new Map<string, Set<string>>();
  const needs = new Map<string, Set<string>>();
  for (const manifest of manifests.filter((m) => state.scenarios.includes(m.id))) {
    for (const role of manifest.roles) {
      const kind = role.kind ?? "text";
      if (kind === "decision" && !decides) continue;
      roles.set(kind, (roles.get(kind) ?? new Set()).add(role.name));
      needs.set(kind, new Set([...(needs.get(kind) ?? []), ...(role.needs ?? [])]));
    }
  }
  return KINDS.filter(({ kind }) => roles.has(kind))
    .map(({ kind }) => ({ kind, roles: [...roles.get(kind)!].sort(), needs: [...needs.get(kind)!].sort() }));
}

/** Where a bundle's models come from: "Local small preset", "Local small, edited", "one model". */
export function bundleSource(config: ConfigDraft, profiles: Record<string, ModelPreset>): string {
  const preset = knownPreset(config, profiles);
  if (preset) return `${profiles[preset]!.label}${hasKinds(config) ? ", edited" : " preset"}`;
  return hasKinds(config) ? "models per kind" : "one model";
}

/** Steps of one kind that do not run on the setup's model for that kind (set per role or per scenario), among the
 *  selected scenarios: what the kind's cell in the setup table does not show. */
export function kindExceptions(
  config: ConfigDraft, manifests: ScenarioManifest[], scenarios: string[], profiles: Record<string, ModelPreset> = {},
): Record<string, { role: string; scenario: string; model: string }[]> {
  const models = bundleModels(config, profiles);
  const out: Record<string, { role: string; scenario: string; model: string }[]> = {};
  for (const manifest of manifests.filter((m) => scenarios.includes(m.id))) {
    for (const role of manifest.roles) {
      const kind = role.kind ?? "text";
      const model = stepModel(config, manifest, role.name, profiles);
      if (model && model !== models[kind]) (out[kind] ??= []).push({ role: role.name, scenario: manifest.title, model });
    }
  }
  return out;
}

/** Capabilities a model lacks of these needs; nothing for a model the catalog does not list (it cannot tell). */
export function lacking(catalog: CatalogItem[], ref: string, needs: string[]): string[] {
  const item = catalog.find((o) => o.ref === splitRef(ref).base);
  return item ? needs.filter((need) => !eligibleModels([item], [need]).length) : [];
}

/** Steps that would run on a model without a capability they need (vision, json_schema, …). Decision steps count
 *  only when the control policy calls an LLM, since they never run otherwise. */
function missingCapabilities(
  state: BuilderState, manifests: ScenarioManifest[], allProfiles: Record<string, ModelPreset>, catalog: CatalogItem[],
): string[] {
  const errors: string[] = [];
  for (const { bundle, name } of expandConfigs(state)) {
    const { config, profiles } = withKinds(bundle, allProfiles);
    const called = llmRoles(bundle.decisions);
    for (const manifest of manifests.filter((m) => state.scenarios.includes(m.id))) {
      for (const role of manifest.roles.filter((r) => (r.needs ?? []).length)) {
        if (role.kind === "decision" && !called.includes(role.name)) continue;
        const model = stepModel(config, manifest, role.name, profiles);
        const missing = lacking(catalog, model, role.needs ?? []);
        if (missing.length) errors.push(`${name}: ${splitRef(model).base} lacks ${missing.join(", ")}, which "${role.name}" in ${manifest.id} needs.`);
      }
    }
  }
  return errors;
}

/** How many trials the run plans (mirrors ExperimentRunner.plan). Not exact with a task split (the manifest counts
 *  every task). */
export function plannedTrials(state: BuilderState, manifests: ScenarioManifest[]): { trials: number; exact: boolean } {
  const selected = new Map(manifests.filter((m) => state.scenarios.includes(m.id)).map((m) => [m.id, m]));
  const runs = expandConfigs(state).flatMap(({ bundle }) => runsIn(bundle, state, manifests));
  const tasks = (id: string) => {
    const total = selected.get(id)?.tasks ?? 0;
    return state.limit ? Math.min(state.limit, total) : total;
  };
  const trials = runs.reduce((n, id) => n + tasks(id), 0) * Math.max(1, state.repeats || 1);
  return { trials, exact: state.split === "all" };
}
