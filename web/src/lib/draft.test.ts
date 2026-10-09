import { beforeEach, describe, expect, it } from "vitest";

import { configForModel, configForPreset, starterConfig, type ConfigDraft } from "./builder";
import { addToDraft, adoptStartPreset, draft, isStarter } from "./draft.svelte";

const starter = (): ConfigDraft => starterConfig("local-small");

describe("adding a scenario setup to the draft", () => {
  beforeEach(() => {
    draft.scenarios = [];
    draft.configs = [starter()];
  });

  it("replaces the untouched starter bundle", () => {
    addToDraft("reflection_sql", configForModel("openai:gpt-5-mini"));
    expect(draft.configs.map((c) => c.roles["*"])).toEqual(["openai:gpt-5-mini"]);
  });

  it("keeps a bundle whose models per kind were edited in the table", () => {
    draft.configs[0]!.kinds = { code: "openai:gpt-5-mini" };
    addToDraft("reflection_sql", configForModel("ollama:qwen3:4b"));
    expect(draft.configs).toHaveLength(2);
    expect(draft.configs[0]!.kinds).toEqual({ code: "openai:gpt-5-mini" });
  });

  it("replaces a starter without a preset (no preset runs here) too", () => {
    draft.configs = [starterConfig("")];
    addToDraft("reflection_sql", configForModel("openai:gpt-5-mini"));
    expect(draft.configs).toHaveLength(1);
    expect(isStarter(draft.configs[0]!)).toBe(false); // the added setup is the user's
  });

  it("counts a changed preset, a typed name or an own policy as chosen", () => {
    expect(isStarter(starter())).toBe(true);
    expect(isStarter({ ...starter(), preset: "some-other-preset" })).toBe(false);
    expect(isStarter(configForPreset("local-small"))).toBe(false); // a preset the user picked, however empty the setup
    expect(isStarter({ ...starter(), named: true })).toBe(false);
    expect(isStarter({ ...starter(), decisions: { policy: "rules", control: "gate" } })).toBe(false);
  });
});

describe("starters follow the preset new setups start from", () => {
  it("move to it (a preset that runs here, or none) and stay starters", () => {
    const configs = [starterConfig("local-small")];
    adoptStartPreset(configs, "openai-mini");
    expect(configs[0]).toMatchObject({ preset: "openai-mini", autoPreset: "openai-mini" });
    adoptStartPreset(configs, "");
    expect(configs[0]).toMatchObject({ preset: "", autoPreset: "" });
    expect(isStarter(configs[0]!)).toBe(true);
  });

  it("leave every preset the user chose, even one unavailable for now", () => {
    const chosen = configForPreset("local-small");
    const switched = { ...starterConfig("openai-mini"), preset: "local-small" };
    adoptStartPreset([chosen, switched], "");
    expect([chosen.preset, switched.preset]).toEqual(["local-small", "local-small"]);
  });
});
