import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";

import { emptyConfig, type BuilderState } from "./builder";
import type { ExperimentConfig, ModelPreset, ScenarioManifest } from "./contracts";
import { SUITES, applySuite, clearSuite, suiteChanges, suiteScenarios } from "./scenario-groups";

const manifest = (id: string, kind: ScenarioManifest["kind"] = "pattern", params: string[] = []): ScenarioManifest => ({
  id,
  title: id.replace(/_/g, " "),
  pattern: "p",
  description: "",
  kind,
  roles: [{ name: kind === "benchmark" ? "model" : "agent", description: "" }],
  params: params.map((name) => ({ name, type: "integer", default: 1, description: "" })) as ScenarioManifest["params"],
  pass_criteria: [],
  requires: [],
  tasks: 10,
});

const MANIFESTS = [
  manifest("reflection_sql", "pattern", ["reflection_rounds"]),
  manifest("reflection_writing", "pattern", ["reflection_rounds"]),
  manifest("chart_codegen"),
  manifest("email_assistant"),
  manifest("gsm8k", "benchmark"),
  manifest("mmlu_pro", "benchmark"),
];
const PRESETS = { "local-small": { label: "Local small", models: { text: "ollama:qwen3:4b" } } } as unknown as Record<string, ModelPreset>;

// The scenarios this build ships (contracts/scenarios/<id>/manifest.json).
const SHIPPED = readdirSync(new URL("../../../contracts/scenarios/", import.meta.url))
  .map((id) => JSON.parse(readFileSync(new URL(`../../../contracts/scenarios/${id}/manifest.json`, import.meta.url), "utf8")) as ScenarioManifest);

const state = (): BuilderState => ({
  name: "custom",
  scenarios: [],
  configs: [{ ...emptyConfig(0), roles: { "*": "openai:gpt-4.1-mini" } }],
  repeats: 1,
  limit: null,
  judge: "",
  arena: false,
  maxCostUsd: null,
  budgetMode: "best_effort",
  split: "all",
});
const suite = (id: string) => SUITES.find((s) => s.id === id)!;

describe("scenario suites", () => {
  it("expand explicit suites only to scenarios available in this build", () => {
    expect(suiteScenarios(suite("smoke"), MANIFESTS)).toEqual(["reflection_sql", "email_assistant"]);
  });

  it("expand benchmark suites by scenario kind", () => {
    expect(suiteScenarios(suite("classic_benchmarks"), MANIFESTS)).toEqual(["gsm8k", "mmlu_pro"]);
  });

  it("fill in what to run and leave the model bundles alone", () => {
    const draft = state();
    const bundles = draft.configs;
    applySuite(draft, suite("smoke"), MANIFESTS, PRESETS);
    expect(draft).toMatchObject({ suite: "smoke", scenarios: ["reflection_sql", "email_assistant"], limit: 3, variants: [] });
    expect(draft.configs).toBe(bundles);
  });

  it("start with a preset bundle when there is none", () => {
    const draft = { ...state(), configs: [] };
    applySuite(draft, suite("smoke"), MANIFESTS, PRESETS);
    expect(draft.configs).toMatchObject([{ preset: "local-small" }]);
  });

  it("bring their method variants; parameters apply to every scenario that has them", () => {
    const draft = state();
    applySuite(draft, suite("reflection"), MANIFESTS, PRESETS);
    expect(draft.variants).toEqual([
      { name: "no-reflection", params: { reflection_rounds: 0 }, decisions: null },
      { name: "self-reflect", params: {}, decisions: null },
    ]);
  });

  it("say what was changed of them, and clear without touching the bundles", () => {
    const draft = state();
    applySuite(draft, suite("reflection"), MANIFESTS, PRESETS);
    expect(suiteChanges(draft, suite("reflection"), MANIFESTS)).toEqual([]);
    draft.scenarios = ["reflection_sql"];
    draft.repeats = 1;
    expect(suiteChanges(draft, suite("reflection"), MANIFESTS)).toEqual(["scenarios", "run settings"]);
    const bundles = draft.configs;
    clearSuite(draft);
    expect(draft).toMatchObject({ suite: "", scenarios: [], variants: [] });
    expect(draft.configs).toBe(bundles);
  });

  it("prepare the critic study: the first setup becomes the baseline the swaps are compared with", () => {
    const draft = state();
    applySuite(draft, suite("critic_study"), MANIFESTS, PRESETS);
    expect(draft.name).toBe("critic-study");
    expect(draft.scenarios).toEqual(["reflection_sql", "chart_codegen"]);
    expect(draft.limit).toBe(3);
    expect(draft.configs.map((c) => c.baseline)).toEqual([true]);
    expect(suite("critic_study").swaps).toEqual({ roles: ["critic"] });
  });
});

// The CLI and the page offer the same experiments: a suite copies its YAML's scenarios, task count, repeats, split,
// judge, arena and setup variants; only the models differ (the page starts from the browser's preset).
describe.each(SUITES.map((s) => [s.id, s] as const))("suite %s matches its CLI experiment", (_, s) => {
  const yaml = parse(readFileSync(new URL(`../../../${s.cli}`, import.meta.url), "utf8")) as ExperimentConfig;

  it("runs the same scenarios with the same settings", () => {
    expect(suiteScenarios(s, SHIPPED).sort()).toEqual([...yaml.scenarios].sort());
    expect(s.limit).toBe(yaml.limit ?? null);
    expect(s.repeats).toBe(yaml.repeats ?? 1);
    expect(s.split ?? "all").toBe(yaml.split ?? "all");
    expect(s.judge ?? "").toBe(yaml.judge ?? "");
    expect(Boolean(s.arena)).toBe(Boolean(yaml.arena?.enabled));
  });

  it("has the YAML's setups for each variant", () => {
    if (yaml.study) {
      expect(yaml.study.roles ?? []).toEqual(s.swaps?.roles ?? []);
      return;
    }
    for (const variant of s.variants ?? []) {
      const config = (yaml.configs ?? []).find((c) => c.name === variant.name);
      expect(config, `${variant.name} in ${s.cli}`).toBeDefined();
      expect(config!.decisions ? { policy: config!.decisions.policy, control: config!.decisions.control } : undefined).toEqual(variant.decisions);
      expect(config!.params).toEqual(variant.params);
    }
  });
});
