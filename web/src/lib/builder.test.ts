import { describe, expect, it } from "vitest";
import { parse } from "yaml";

import type { CatalogItem } from "./backend";
import { defaultRoleNeeds, eligibleModels, emptyConfig, roleSlots, toExperiment, toYaml, validate, type BuilderState } from "./builder";
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
    expect(experiment.configs[0]).toEqual({ name: "p", roles: { "*": "m" }, decisions: { policy: "llm", control: "gate" }, scenarios: ["support_desk"] });
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
