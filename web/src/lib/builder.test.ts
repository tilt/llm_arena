import { describe, expect, it } from "vitest";
import { parse } from "yaml";

import type { CatalogItem } from "./backend";
import { bundleModels, bundleSource, configForModel, configForPreset, defaultRoleNeeds, eligibleModels, emptyConfig, expandConfigs, kindExceptions, kindsUsed, lacking, plannedTrials, roleSlots, stepModel, shortModel, suggestName, swapSetups, toExperiment, toYaml, validate, type BuilderState, type ConfigDraft } from "./builder";
import type { ScenarioManifest } from "./contracts";

const manifest = (id: string, roles: ScenarioManifest["roles"], requires: ScenarioManifest["requires"] = []): ScenarioManifest => ({
  id, title: id, pattern: "p", description: "", kind: "pattern", roles, params: [], pass_criteria: [], requires, tasks: 1,
});
const MANIFESTS = [
  manifest("reflection_sql", [{ name: "generator", description: "" }, { name: "critic", description: "", fallback: "generator" }]),
  manifest("chart_codegen", [{ name: "generator", description: "" }, { name: "critic", description: "", needs: ["vision"] }], ["sandbox"]),
  { ...manifest("support_desk", [{ name: "agent", description: "" }, { name: "decider", description: "", fallback: "agent" }]), supports_decisions: true },
];
const model = (ref: string, vision: boolean): CatalogItem =>
  ({ ref, source: "openai", spec: { name: ref, provider: "openai", model: ref, capabilities: { vision } } }) as CatalogItem;

const state = (over: Partial<BuilderState> = {}): BuilderState => ({
  name: "exp", scenarios: ["reflection_sql"], configs: [{ ...emptyConfig(0), roles: { "*": "openai:gpt-4.1-nano" } }],
  repeats: 1, limit: null, judge: "", arena: false, maxCostUsd: null, budgetMode: "best_effort", split: "all", ...over,
});

describe("role slots", () => {
  it("merges roles and needs across scenarios", () => {
    const slots = roleSlots(MANIFESTS, ["reflection_sql", "chart_codegen"]);
    const critic = slots.find((s) => s.name === "critic")!;
    expect(critic.needs).toEqual(["vision"]);
    expect(critic.optional).toBe(false); // optional in reflection_sql, required in chart_codegen
    expect(slots.find((s) => s.name === "generator")!.scenarios).toEqual(["reflection_sql", "chart_codegen"]);
  });

  it("filters models by capability and derives needs of the default role", () => {
    const catalog = [model("a", true), model("b", false)];
    expect(eligibleModels(catalog, ["vision"]).map((m) => m.ref)).toEqual(["a"]);
    const slots = roleSlots(MANIFESTS, ["chart_codegen"]);
    expect(defaultRoleNeeds(slots, { ...emptyConfig(0), roles: {} })).toEqual(["vision"]);
    expect(defaultRoleNeeds(slots, { ...emptyConfig(0), roles: { critic: "a" } })).toEqual([]);
  });
});

describe("validation", () => {
  it("accepts a complete draft and reports what is missing", () => {
    expect(validate(state(), MANIFESTS, true)).toEqual([]);
    const errors = validate(state({ scenarios: ["chart_codegen"], configs: [{ ...emptyConfig(0), roles: { generator: "x" } }] }), MANIFESTS, false);
    expect(errors.some((e) => e.includes('"critic"'))).toBe(true);
    expect(errors.some((e) => e.includes("Code execution is unavailable"))).toBe(true);
    expect(validate(state({ arena: true }), MANIFESTS, true)).toContain("Arena battles need a judge model.");
  });
});

describe("experiment output", () => {
  it("produces the config the CLI runs", () => {
    const draft = state({ limit: 3, judge: "openai:gpt-4.1-mini", arena: true, maxCostUsd: 2,
      configs: [{ name: "c", roles: { "*": "m", critic: "" }, scenarioParams: { reflection_sql: { feedback: "sql_only" }, chart_codegen: { x: 1 } }, scenarioRoles: { reflection_sql: { critic: "big" }, chart_codegen: { critic: "vlm" } }, decisions: null }] });
    const experiment = toExperiment(draft);
    expect(experiment).toEqual({
      name: "exp", scenarios: ["reflection_sql"], repeats: 1, limit: 3, judge: "openai:gpt-4.1-mini", arena: { enabled: true },
      max_cost_usd: 2, configs: [{ name: "c", roles: { "*": "m" }, scenario_params: { reflection_sql: { feedback: "sql_only" } }, scenario_roles: { reflection_sql: { critic: "big" } } }],
    });
    expect(parse(toYaml(experiment))).toEqual(experiment);
  });

  it("emits strict budget mode only when selected", () => {
    expect(toExperiment(state({ maxCostUsd: 1, budgetMode: "strict" })).budget_mode).toBe("strict");
    expect(toExperiment(state({ maxCostUsd: 1, budgetMode: "best_effort" })).budget_mode).toBeUndefined();
  });
});

describe("control policies", () => {
  const withPolicy = (policy: "llm" | "jev" | "ollaya") =>
    state({ scenarios: ["reflection_sql", "support_desk"], split: "test",
      configs: [{ ...emptyConfig(0), name: "p", roles: { "*": "m" }, decisions: { policy, control: "gate" } }] });

  it("restricts a policy config to the scenarios that support one", () => {
    const experiment = toExperiment(withPolicy("llm"), MANIFESTS);
    expect(experiment.configs?.[0]).toEqual({ name: "p", roles: { "*": "m" }, decisions: { policy: "llm", control: "gate" }, scenarios: ["support_desk"] });
    expect(experiment.split).toBe("test");
  });

  it("reports unsupported selections and unavailable decision services", () => {
    const none = state({ configs: [{ ...emptyConfig(0), roles: { "*": "m" }, decisions: { policy: "rules" } }] });
    expect(validate(none, MANIFESTS, true).some((e) => e.includes("supports a control policy"))).toBe(true);
    const status = { jev: "no key", ollaya: "available" };
    expect(validate(withPolicy("jev"), MANIFESTS, true, status).some((e) => e.includes("Jev is unavailable"))).toBe(true);
    expect(validate(withPolicy("ollaya"), MANIFESTS, true, status)).toEqual([]);
    expect(validate(withPolicy("llm"), MANIFESTS, true, { jev: "no key", ollaya: "down" })).toEqual([]);
  });
});

describe("replacement studies as setups", () => {
  const sql = manifest("reflection_sql", [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", fallback: "generator", kind: "text" }]);
  const chart = manifest("chart_codegen", [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", needs: ["vision"], kind: "vision" }]);
  const profiles = { weak: { label: "Weak", models: { text: "weak", code: "weak", vision: "vlm" } } } as never;
  const catalog = [model("strong", false), model("weak", false), model("vlm", true)];
  const base = (): ConfigDraft => ({ ...configForPreset("weak"), name: "weak", named: true, id: "weak-id" });

  it("swap one step per setup, only where the candidate can do it and changes something", () => {
    const baseline = base();
    const { setups, skipped } = swapSetups(baseline, ["strong", "weak"], ["critic", "generator"], [sql, chart], profiles, catalog);
    expect(setups.map((s) => [s.name, s.only, s.swap])).toEqual([
      ["critic→strong", ["reflection_sql"], { role: "critic", candidate: "strong", from: "weak-id" }],
      ["generator→strong", ["reflection_sql", "chart_codegen"], { role: "generator", candidate: "strong", from: "weak-id" }],
    ]);
    expect(setups[0]!.id).not.toBe("weak-id");
    expect(setups[0]!.scenarioRoles).toEqual({ reflection_sql: { critic: "strong" } });
    expect(baseline.scenarioRoles).toEqual({}); // the baseline itself is untouched
    expect(skipped).toContainEqual({ role: "critic", candidate: "strong", scenario: "chart_codegen", why: "lacks vision" });
    expect(skipped).toContainEqual({ role: "generator", candidate: "weak", scenario: "reflection_sql", why: "the baseline already runs it" });
  });

  it("change exactly one step, even where another step falls back to the swapped one", () => {
    const { setups } = swapSetups({ ...configForModel("weak"), named: true, id: "w" }, ["strong"], ["generator"], [sql], {}, catalog);
    // Without a preset the critic follows the generator; it stays on the baseline's model.
    expect(setups[0]!.scenarioRoles).toEqual({ reflection_sql: { generator: "strong", critic: "weak" } });
    expect(stepModel(setups[0]!, sql, "critic")).toBe("weak");
  });

  it("compare every setup with the baseline under the same variant, running swaps only where they apply", () => {
    const { setups } = swapSetups(base(), ["strong"], ["critic"], [sql, chart], profiles, catalog);
    const configs = [{ ...base(), baseline: true }, ...setups];
    const plain = toExperiment(state({ scenarios: ["reflection_sql", "chart_codegen"], configs }), [sql, chart], profiles).configs!;
    expect(plain[0]).not.toHaveProperty("compare_to");
    expect(plain[0]).not.toHaveProperty("scenarios");
    expect(plain[1]).toMatchObject({
      name: "critic→strong", compare_to: "weak", scenarios: ["reflection_sql"],
      scenario_roles: { reflection_sql: { critic: "strong" } }, study: { kind: "swap", role: "critic", candidate: "strong" },
    });
    const variants = [{ name: "a", params: {}, decisions: null }, { name: "b", params: {}, decisions: null }];
    const both = toExperiment(state({ scenarios: ["reflection_sql", "chart_codegen"], configs, variants }), [sql, chart], profiles).configs!;
    expect(both.map((c) => [c.name, c.compare_to])).toEqual([["weak/a", undefined], ["weak/b", undefined], ["critic→strong/a", "weak/a"], ["critic→strong/b", "weak/b"]]);
    expect(plannedTrials(state({ scenarios: ["reflection_sql", "chart_codegen"], configs }), [sql, chart]).trials).toBe(3);
  });

  it("keep comparing a swap with the setup it was made from, whichever setup is the baseline", () => {
    const { setups } = swapSetups(base(), ["strong"], ["critic"], [sql], profiles, catalog);
    const other = { ...configForModel("strong"), name: "other", named: true, id: "other-id" };
    const compared = (configs: ConfigDraft[]) =>
      toExperiment(state({ scenarios: ["reflection_sql"], configs }), [sql], profiles).configs!.map((c) => [c.name, c.compare_to]);
    expect(compared([base(), other, ...setups])).toEqual([["weak", undefined], ["other", undefined], ["critic→strong", "weak"]]);
    expect(compared([base(), { ...other, baseline: true }, ...setups])).toEqual([["weak", "other"], ["other", undefined], ["critic→strong", "weak"]]);
  });

  it("refuse a swap whose setup was removed or changed since", () => {
    const { setups } = swapSetups(base(), ["strong"], ["critic"], [sql], profiles, catalog);
    const errors = (configs: ConfigDraft[]) => validate(state({ scenarios: ["reflection_sql"], configs }), [sql], true, {}, profiles);
    expect(errors([base(), ...setups])).toEqual([]);
    expect(errors(setups)).toContain("critic→strong: the setup it swaps a step of was removed; remove it or add the swaps again.");
    const edited = { ...base(), kinds: { code: "strong" } };
    expect(errors([edited, ...setups])).toContain("critic→strong: differs from weak in more than the critic now; remove it or add the swaps again.");
  });

  it("refuse two baselines and a setup that runs nowhere", () => {
    const configs = [{ ...base(), baseline: true }, { ...base(), name: "other", baseline: true, only: ["chart_codegen"] }];
    const errors = validate(state({ scenarios: ["reflection_sql"], configs }), [sql, chart], true, {}, profiles);
    expect(errors).toContain("Mark only one setup as the baseline.");
    expect(errors).toContain("other: runs in none of the selected scenarios.");
  });
});

describe("suggested setup names", () => {
  const presets = { "local-small": { label: "Local small", models: { text: "ollama:qwen3:4b#reasoning=none" } } };
  const config = (extra: Partial<ConfigDraft>): ConfigDraft => ({ ...emptyConfig(0), ...extra });

  it("names a setup after what runs", () => {
    expect(shortModel("ollama:qwen3.8:27b-mlx")).toBe("qwen3.8-27b-mlx");
    expect(shortModel("ollama:qwen3:4b#reasoning=none")).toBe("qwen3-4b-nothink");
    expect(suggestName(config({ preset: "local-small" }), presets)).toBe("local-small");
    expect(suggestName(config({ roles: { "*": "ollama:qwen3.8:27b-mlx" } }), presets)).toBe("qwen3.8-27b-mlx");
    expect(suggestName(config({ preset: "local-small", scenarioRoles: { chart: { critic: "openai:gpt-5-mini" } } }), presets))
      .toBe("local-small+critic-gpt-5-mini");
    // A setup loaded from the leaderboard binds every step; one model for all of them reads as that model.
    expect(suggestName(config({ scenarioRoles: { chart: { generator: "ollama:qwen3:14b", critic: "ollama:qwen3:14b" } } }), presets))
      .toBe("qwen3-14b");
    expect(suggestName(config({ roles: { "*": "ollama:qwen3:14b" }, decisions: { policy: "ollaya" } as ConfigDraft["decisions"] }), presets))
      .toBe("qwen3-14b+ollaya");
  });

  it("ignores a preset the page does not know and scenarios not selected", () => {
    expect(suggestName(config({ preset: "gone", roles: { "*": "ollama:gemma4:26b" } }), presets)).toBe("gemma4-26b");
    expect(suggestName(config({ roles: { "*": "ollama:qwen3:14b" }, scenarioRoles: { other: { critic: "openai:gpt-5-mini" } } }), presets, ["chart"]))
      .toBe("qwen3-14b");
  });
});

describe("names for recorded setups", () => {
  it("names a run's setup after the models it actually ran on", async () => {
    const { nameFromSetup } = await import("./setups");
    const qwen = { provider: "ollama", model: "qwen3.8:27b-mlx" };
    expect(nameFromSetup({ roles: { researcher: qwen, writer: qwen, reviewer: qwen } })).toBe("qwen3.8-27b-mlx");
    expect(nameFromSetup({ roles: { agent: { provider: "ollama", model: "qwen3:4b", reasoning_effort: "none" } }, decisions: { policy: "rules" } }))
      .toBe("qwen3-4b-nothink+rules");
  });
});

const PROFILES = {
  "local-small": { label: "Local small", models: { text: "ollama:qwen3:4b", code: "ollama:qwen3:4b", vision: "ollama:qwen3-vl:8b" } },
} as never;

describe("model bundles", () => {
  it("a model pick becomes a bundle that runs every step on it", () => {
    expect(configForModel("openai:gpt-4.1-mini#reasoning=low")).toMatchObject({
      name: "gpt-4.1-mini-low", roles: { "*": "openai:gpt-4.1-mini#reasoning=low" }, preset: "",
    });
  });

  it("have a model per kind: their own, else the preset's, else their one model", () => {
    const edited = { ...configForPreset("local-small"), kinds: { code: "openai:gpt-5-mini", text: "#reasoning=low" } };
    expect(bundleModels(edited, PROFILES)).toMatchObject({
      code: "openai:gpt-5-mini", text: "ollama:qwen3:4b#reasoning=low", vision: "ollama:qwen3-vl:8b",
    });
    expect(bundleModels(configForModel("m"), PROFILES)).toMatchObject({ text: "m", code: "m", vision: "m" });
    expect(bundleSource(edited, PROFILES)).toBe("Local small, edited");
    expect(bundleSource(configForPreset("local-small"), PROFILES)).toBe("Local small preset");
    expect(bundleSource(configForModel("m"), PROFILES)).toBe("one model");
  });

  it("with models of their own run as a preset of their own, which never shadows a real one", () => {
    const edited = { ...configForPreset("local-small"), name: "local-small", kinds: { code: "openai:gpt-5-mini" } };
    const experiment = toExperiment(state({ configs: [edited] }), MANIFESTS, PROFILES);
    expect(experiment.configs?.[0]).toMatchObject({ name: "local-small", preset: "local-small-models", roles: {} });
    expect(experiment.presets?.["local-small-models"]?.models).toMatchObject({ code: "openai:gpt-5-mini", text: "ollama:qwen3:4b" });
    expect(experiment.presets).not.toHaveProperty("local-small");
    expect(stepModel(edited, MANIFESTS[0]!, "generator", PROFILES)).toBe("ollama:qwen3:4b"); // generator is text by default
  });

  it("list the steps of a kind that run on another model than the kind's cell shows", () => {
    const config = { ...configForModel("m"), roles: { "*": "m", critic: "x" }, scenarioRoles: { chart_codegen: { generator: "y" }, other: { a: "z" } } };
    expect(kindExceptions(config, MANIFESTS, ["reflection_sql", "chart_codegen"])).toEqual({
      text: [
        { role: "critic", scenario: "reflection_sql", model: "x" },
        { role: "generator", scenario: "chart_codegen", model: "y" },
        { role: "critic", scenario: "chart_codegen", model: "x" },
      ],
    });
    expect(kindExceptions(configForModel("m"), MANIFESTS, ["reflection_sql"])).toEqual({});
  });

  it("refuse a step on a model without a capability it needs", () => {
    const catalog = [model("openai:a", true), model("openai:b", false)];
    expect(lacking(catalog, "openai:b#reasoning=low", ["vision"])).toEqual(["vision"]);
    expect(lacking(catalog, "unlisted:c", ["vision"])).toEqual([]); // the catalog cannot tell
    const draft = (ref: string) => state({ scenarios: ["chart_codegen"], configs: [{ ...configForModel(ref), name: "s" }] });
    expect(validate(draft("openai:b"), MANIFESTS, true, {}, {}, catalog)).toContain('s: openai:b lacks vision, which "critic" in chart_codegen needs.');
    expect(validate(draft("openai:a"), MANIFESTS, true, {}, {}, catalog)).toEqual([]);
  });
});

describe("variants", () => {
  const variants = [
    { name: "no-reflection", params: { reflection_rounds: 0 }, decisions: null },
    { name: "rules-gate", params: {}, decisions: { policy: "rules", control: "gate" } as const },
  ];

  it("run with every bundle, named bundle/variant; a variant's policy replaces the bundle's", () => {
    const configs = [{ ...configForModel("a"), name: "a", decisions: { policy: "llm" as const } }, { ...configForModel("b"), name: "b" }];
    const draft = state({ scenarios: ["reflection_sql", "support_desk"], configs, variants });
    expect(expandConfigs(draft).map((c) => c.name)).toEqual(["a/no-reflection", "a/rules-gate", "b/no-reflection", "b/rules-gate"]);
    const out = toExperiment(draft, MANIFESTS).configs!;
    expect(out[0]).toMatchObject({ name: "a/no-reflection", params: { reflection_rounds: 0 } });
    expect(out[0]).not.toHaveProperty("decisions");
    expect(out[1]).toMatchObject({ decisions: { policy: "rules", control: "gate" }, scenarios: ["support_desk"] });
  });

  it("must have unique names", () => {
    const draft = state({ variants: [variants[0]!, { ...variants[0]!, params: {} }] });
    expect(validate(draft, MANIFESTS, true)).toContain("Variant names must be unique.");
  });

  it("show decision steps only when a policy calls an LLM", () => {
    const draft = state({ scenarios: ["support_desk"], configs: [configForModel("m")] });
    const withKinds = (d: BuilderState) => kindsUsed(d, MANIFESTS.map((m) => ({ ...m, roles: m.roles.map((r) => ({ ...r, kind: r.name === "decider" ? "decision" as const : "agent" as const })) })));
    expect(withKinds(draft).map((k) => k.kind)).toEqual(["agent"]);
    const llm = { ...draft, variants: [{ name: "llm", params: {}, decisions: { policy: "llm" as const } }] };
    expect(withKinds(llm).map((k) => k.kind)).toEqual(["agent", "decision"]);
    expect(kindsUsed(state({ scenarios: ["chart_codegen"] }), MANIFESTS)).toEqual([{ kind: "text", roles: ["critic", "generator"], needs: ["vision"] }]);
  });
});

describe("planned trials", () => {
  const sized = MANIFESTS.map((m, i) => ({ ...m, tasks: [10, 4, 6][i]! }));

  it("multiply setups, tasks (capped by the limit) and repeats; a policy runs only where it applies", () => {
    const configs = [emptyConfig(0), { ...emptyConfig(1), decisions: { policy: "rules", control: "gate" } as const }];
    const draft = state({ scenarios: ["reflection_sql", "support_desk"], configs, limit: 5, repeats: 2 });
    // setup 1: (5 + 5) tasks; setup 2 (policy): support_desk only, 5 tasks; times 2 repeats
    expect(plannedTrials(draft, sized)).toEqual({ trials: 30, exact: true });
  });

  it("multiply by variants", () => {
    const variants = [{ name: "a", params: {}, decisions: null }, { name: "b", params: {}, decisions: null }];
    expect(plannedTrials(state({ variants }), sized)).toEqual({ trials: 20, exact: true });
  });

  it("are an upper bound with a task split", () => {
    expect(plannedTrials(state({ split: "dev" }), sized)).toEqual({ trials: 10, exact: false });
  });
});
