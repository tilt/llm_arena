import { describe, expect, it } from "vitest";

import { describeRef, joinRef, modelFor, splitRef } from "./baselines";
import { boundModel, emptyConfig, toExperiment, validate, type BuilderState } from "./builder";
import type { BaselineProfile, ScenarioManifest } from "./contracts";

const PROFILE: BaselineProfile = { label: "Local small", models: { text: "ollama:qwen3:4b#reasoning=none", vision: "ollama:qwen3-vl:8b" } };

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

describe("baselines in the builder", () => {
  const manifest = { id: "chart", title: "c", pattern: "p", description: "", kind: "pattern", params: [], pass_criteria: [], tasks: 1,
    roles: [{ name: "generator", description: "", kind: "code" }, { name: "critic", description: "", kind: "vision", needs: ["vision"] }] } as ScenarioManifest;
  const config = { ...emptyConfig(0), name: "c", roles: {}, baseline: "local-small", scenarioRoles: { chart: { critic: "openai:gpt-5-mini" } } };
  const state: BuilderState = { name: "e", scenarios: ["chart"], configs: [config], repeats: 1, limit: 1, judge: "", arena: false, maxCostUsd: 1, split: "all" };

  it("binds explicit roles first, then the baseline by kind", () => {
    const profiles = { "local-small": PROFILE };
    expect(boundModel(config, "chart", "critic", "vision", profiles)).toBe("openai:gpt-5-mini");
    expect(boundModel(config, "chart", "generator", "code", profiles)).toBe("ollama:qwen3:4b#reasoning=none");
  });

  it("accepts a baseline instead of a model per role and ships the profile with the experiment", () => {
    expect(validate(state, [manifest], true)).toEqual([]);
    const experiment = toExperiment(state, [manifest], { "local-small": PROFILE });
    expect(experiment.configs?.[0]).toMatchObject({ baseline: "local-small", scenario_roles: { chart: { critic: "openai:gpt-5-mini" } } });
    expect(experiment.baselines).toEqual({ "local-small": PROFILE });
  });
});
