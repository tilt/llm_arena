import { describe, expect, it } from "vitest";

import { applyOverride, describeRef, isOverride, joinRef, modelFor, overrideReasoning, splitRef, thinkingOverride, usablePresets } from "./presets";
import { boundModel, emptyConfig, inheritedModel, stepModel, suggestName, toExperiment, validate, type BuilderState } from "./builder";
import type { CatalogItem } from "./backend";
import type { ModelPreset, ScenarioManifest } from "./contracts";

const PROFILE: ModelPreset = { label: "Local small", models: { text: "ollama:qwen3:4b#reasoning=none", vision: "ollama:qwen3-vl:8b" } };

describe("model references with settings", () => {
  it("split, join and describe", () => {
    expect(splitRef("ollama:qwen3:4b#reasoning=none,tools=json")).toEqual({ base: "ollama:qwen3:4b", reasoning: "none", rest: ["tools=json"] });
    expect(joinRef("openai:gpt-5-mini", "low")).toBe("openai:gpt-5-mini#reasoning=low");
    expect(joinRef("openai:gpt-5-mini", "")).toBe("openai:gpt-5-mini");
    expect(describeRef("ollama:qwen3:4b#reasoning=none")).toBe("qwen3:4b · thinking off");
  });

  it("falls back to the text model for kinds a profile does not set", () => {
    expect(modelFor(PROFILE, "vision")).toBe("ollama:qwen3-vl:8b");
    expect(modelFor(PROFILE, "code")).toBe("ollama:qwen3:4b#reasoning=none");
  });
});

describe("presets in the builder", () => {
  const manifest = { id: "chart", title: "c", pattern: "p", description: "", kind: "pattern", params: [], pass_criteria: [], tasks: 1,
    roles: [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", kind: "vision", needs: ["vision"] }] } as ScenarioManifest;
  const config = { ...emptyConfig(0), name: "c", roles: {}, preset: "local-small", scenarioRoles: { chart: { critic: "openai:gpt-5-mini" } } };
  const state: BuilderState = { name: "e", scenarios: ["chart"], configs: [config], repeats: 1, limit: 1, judge: "", arena: false, maxCostUsd: 1, budgetMode: "best_effort", split: "all" };

  it("binds explicit roles first, then the preset by kind", () => {
    const profiles = { "local-small": PROFILE };
    expect(boundModel(config, "chart", "critic", "vision", profiles)).toBe("openai:gpt-5-mini");
    expect(boundModel(config, "chart", "generator", "code", profiles)).toBe("ollama:qwen3:4b#reasoning=none");
  });

  it("accepts a preset instead of a model per role and ships it with the experiment", () => {
    expect(validate(state, [manifest], true, {}, { "local-small": PROFILE })).toEqual([]);
    const experiment = toExperiment(state, [manifest], { "local-small": PROFILE });
    expect(experiment.configs?.[0]).toMatchObject({ preset: "local-small", scenario_roles: { chart: { critic: "openai:gpt-5-mini" } } });
    expect(experiment.presets).toEqual({ "local-small": PROFILE });
  });

  it("runs what the page shows: an unknown preset is dropped, a known one drops the hidden default model", () => {
    const withDefault = { ...state, configs: [{ ...config, roles: { "*": "ollama:gemma4:26b" } }] };
    const unknown = toExperiment(withDefault, [manifest], {}).configs?.[0];
    expect(unknown).not.toHaveProperty("preset");
    expect(unknown?.roles).toEqual({ "*": "ollama:gemma4:26b" });
    const known = toExperiment(withDefault, [manifest], { "local-small": PROFILE }).configs?.[0];
    expect(known).toMatchObject({ preset: "local-small", roles: {} });
    // Without the preset loaded, steps need models of their own.
    expect(validate(state, [manifest], true)).toContainEqual(expect.stringContaining('"generator"'));
  });
});

describe("thinking overrides: the inherited model with other thinking", () => {
  it("apply to whatever model the step inherits", () => {
    expect(isOverride(thinkingOverride("low"))).toBe(true);
    expect(isOverride("ollama:qwen3:4b")).toBe(false);
    expect(applyOverride("#reasoning=low", "ollama:qwen3:4b#reasoning=none")).toBe("ollama:qwen3:4b#reasoning=low");
    expect(applyOverride("#reasoning=low", "openai:gpt-5-mini#tools=json")).toBe("openai:gpt-5-mini#reasoning=low,tools=json");
    // "model default" drops the inherited setting instead of being lost in the round trip.
    expect(thinkingOverride("")).toBe("#reasoning=default");
    expect(overrideReasoning("#reasoning=default")).toBe("");
    expect(applyOverride(thinkingOverride(""), "ollama:qwen3:4b#reasoning=none")).toBe("ollama:qwen3:4b");
    expect(applyOverride("#reasoning=low", "")).toBe(""); // nothing to inherit yet
    expect(applyOverride("openai:gpt-5-mini", "ollama:qwen3:4b")).toBe("openai:gpt-5-mini"); // concrete stays
  });

  const manifest = { id: "sql", title: "s", pattern: "p", description: "", kind: "pattern", params: [], pass_criteria: [], tasks: 1,
    roles: [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", fallback: "generator" }] } as ScenarioManifest;
  const profiles = { "local-small": PROFILE };
  const withPreset = { ...emptyConfig(0), name: "c", roles: {}, preset: "local-small", scenarioRoles: { sql: { critic: "#reasoning=low" } } };

  it("keep following the preset's model", () => {
    expect(inheritedModel(withPreset, manifest, "critic", profiles)).toBe("ollama:qwen3:4b#reasoning=none");
    expect(stepModel(withPreset, manifest, "critic", profiles)).toBe("ollama:qwen3:4b#reasoning=low");
    const other = { "local-small": { ...PROFILE, models: { text: "openai:gpt-5-mini" } } };
    expect(stepModel(withPreset, manifest, "critic", other)).toBe("openai:gpt-5-mini#reasoning=low");
  });

  it("inherit from the fallback step without a preset", () => {
    const config = { ...emptyConfig(0), roles: { "*": "" }, scenarioRoles: { sql: { generator: "ollama:qwen3:14b#reasoning=none", critic: "#reasoning=high" } } };
    expect(inheritedModel(config, manifest, "critic")).toBe("ollama:qwen3:14b#reasoning=none");
    expect(stepModel(config, manifest, "critic")).toBe("ollama:qwen3:14b#reasoning=high");
  });

  it("reach the engine as concrete references", () => {
    const state: BuilderState = { name: "e", scenarios: ["sql"], configs: [withPreset], repeats: 1, limit: null, judge: "", arena: false,
      maxCostUsd: null, budgetMode: "best_effort", split: "all" };
    expect(validate(state, [manifest], true, {}, profiles)).toEqual([]);
    expect(toExperiment(state, [manifest], profiles).configs?.[0]?.scenario_roles).toEqual({ sql: { critic: "ollama:qwen3:4b#reasoning=low" } });
    expect(boundModel(withPreset, "sql", "critic", "text", profiles)).toBe("ollama:qwen3:4b#reasoning=low");
    expect(suggestName(withPreset, profiles)).toBe("local-small+critic-low");
  });

  it("role-level thinking overrides expand per selected scenario", () => {
    const roleOverride = { ...emptyConfig(0), name: "c", roles: { critic: "#reasoning=low" }, preset: "local-small" };
    const state: BuilderState = { name: "e", scenarios: ["sql"], configs: [roleOverride], repeats: 1, limit: null, judge: "", arena: false,
      maxCostUsd: null, budgetMode: "best_effort", split: "all" };

    expect(validate(state, [manifest], true, {}, profiles)).toEqual([]);
    expect(stepModel(roleOverride, manifest, "critic", profiles)).toBe("ollama:qwen3:4b#reasoning=low");
    expect(toExperiment(state, [manifest], profiles).configs?.[0]).toMatchObject({
      preset: "local-small",
      roles: {},
      scenario_roles: { sql: { critic: "ollama:qwen3:4b#reasoning=low" } },
    });
    expect(suggestName(roleOverride, profiles)).toBe("local-small+critic-low");
  });

  it("are reported when there is no model to change", () => {
    const config = { ...emptyConfig(0), roles: { "*": "" }, scenarioRoles: { sql: { critic: "#reasoning=low" } } };
    const state: BuilderState = { name: "e", scenarios: ["sql"], configs: [config], repeats: 1, limit: null, judge: "", arena: false,
      maxCostUsd: null, budgetMode: "best_effort", split: "all" };
    expect(validate(state, [manifest], true)).toContainEqual(expect.stringContaining("changes the thinking"));
    expect(toExperiment(state, [manifest]).configs?.[0]).not.toHaveProperty("scenario_roles");
  });

  it("reports role-level thinking overrides when there is no inherited model", () => {
    const config = { ...emptyConfig(0), roles: { critic: "#reasoning=low" } };
    const state: BuilderState = { name: "e", scenarios: ["sql"], configs: [config], repeats: 1, limit: null, judge: "", arena: false,
      maxCostUsd: null, budgetMode: "best_effort", split: "all" };
    expect(validate(state, [manifest], true)).toContainEqual(expect.stringContaining('"critic" changes the thinking'));
    expect(toExperiment(state, [manifest]).configs?.[0]).not.toHaveProperty("roles.critic");
  });
});

describe("profiles in browser mode", () => {
  it("offers only profiles a web page can run, without local decision services", () => {
    const profiles = {
      "local-small": { label: "Local small", models: { text: "ollama:qwen3:4b#reasoning=none" }, decision_service: "ollaya:winnow:e4b" },
      "openai-mini": { label: "OpenAI mini", models: { text: "openai:gpt-5-mini#reasoning=low" }, decision_service: "ollaya:winnow:e4b" },
    };
    expect(Object.keys(usablePresets(profiles, true))).toEqual(["openai-mini"]);
    expect(usablePresets(profiles, true)["openai-mini"]!.decision_service).toBeNull();
    expect(Object.keys(usablePresets(profiles, false))).toEqual(["local-small", "openai-mini"]);
  });

  it("keeps profiles on named endpoints, which a page can reach", () => {
    const profiles = {
      "gpu": { label: "GPU box", models: { text: "gpu-box:Qwen/Qwen3-32B" } },
      "env-compatible": { label: "Env endpoint", models: { text: "openai_compatible:qwen3" } },
    };
    expect(Object.keys(usablePresets(profiles, true))).toEqual(["gpu"]);
  });
});

describe("thinking settings per model", () => {
  const item = (provider: string, reasoning: boolean) =>
    ({ ref: `${provider}:m`, source: provider, spec: { name: "m", provider, model: "m", capabilities: { reasoning } } }) as unknown as CatalogItem;

  it("offers only what the chosen model accepts", async () => {
    const { thinkingLevels } = await import("./presets");
    const values = (base: string, it?: CatalogItem) => thinkingLevels(base, it).map((t) => t.value);
    expect(values("ollama:m", item("ollama", true))).toEqual(["", "none", "low", "medium", "high"]);
    expect(values("openai:m", item("openai", true))).toContain("none");
    expect(values("anthropic:m", item("anthropic", true))).not.toContain("none"); // Claude has no "thinking off"
    expect(values("lmstudio:m", item("lmstudio", true))).toEqual([]);           // LM Studio ignores the setting
    expect(values("ollama:m", item("ollama", false))).toEqual([]);              // the model does not think
    expect(values("ollama:gone")).toContain("none");                             // unknown now: keep what was saved
    expect(values("")).toEqual([]);
  });

  it("a leaderboard setup keeps its thinking setting without an alias", async () => {
    const { configFromSetup } = await import("./setups");
    const { config, exact } = configFromSetup("chart", "x", {
      roles: { critic: { provider: "ollama", model: "qwen3:4b", reasoning_effort: "none" }, generator: { provider: "openai", model: "gpt-5-mini" } },
    }, {});
    expect(config.scenarioRoles.chart).toEqual({ critic: "ollama:qwen3:4b#reasoning=none", generator: "openai:gpt-5-mini" });
    expect(exact).toBe(true);
  });
});
