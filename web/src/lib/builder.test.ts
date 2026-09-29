import { describe, expect, it } from "vitest";
import { parse } from "yaml";

import type { CatalogItem } from "./backend";
import { defaultRoleNeeds, eligibleModels, emptyConfig, roleSlots, shortModel, studyConfigs, suggestName, toExperiment, toYaml, validate, type BuilderState, type ConfigDraft } from "./builder";
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
  repeats: 1, limit: null, judge: "", arena: false, maxCostUsd: null, split: "all", ...over,
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
    expect(errors.some((e) => e.includes("cannot execute code"))).toBe(true);
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

describe("replacement studies", () => {
  const sql = manifest("reflection_sql", [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", fallback: "generator", kind: "text" }]);
  const chart = manifest("chart_codegen", [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", needs: ["vision"], kind: "vision" }]);
  const profile = { label: "Weak", models: { text: "weak", code: "weak", vision: "vlm" } };

  it("previews the baseline plus one config per role and candidate, like the engine", () => {
    const study = { baseline: "weak", candidates: ["strong", "weak"], roles: [], decisionControl: "gate" as const };
    const noVision = (_: string, needs: string[]) => !needs.includes("vision");
    expect(studyConfigs(study, [sql, chart], profile, noVision)).toEqual([
      { name: "baseline", scenarios: ["reflection_sql", "chart_codegen"] },
      { name: "critic→strong", scenarios: ["reflection_sql"] },
      { name: "generator→strong", scenarios: ["chart_codegen", "reflection_sql"] },
    ]);
  });

  it("exports a study experiment", () => {
    const experiment = toExperiment(state({ scenarios: ["reflection_sql"], study: { baseline: "weak", candidates: ["strong"], roles: ["critic"], decisionControl: "gate" } }), [sql], { weak: profile });
    expect(experiment.study).toEqual({ baseline: "weak", candidates: ["strong"], roles: ["critic"], decision_control: "gate" });
    expect(experiment.configs).toBeUndefined();
    expect(experiment.presets).toEqual({ weak: profile });
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
