import { beforeEach, describe, expect, it } from "vitest";

import { configForModel, emptyConfig, type ConfigDraft } from "./builder";
import { addToDraft, draft, isStarter } from "./draft.svelte";
import { activePreset } from "./presets";

const starter = (): ConfigDraft => ({ ...emptyConfig(0), preset: activePreset() });

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

  it("counts a changed preset, a typed name or an own policy as chosen", () => {
    expect(isStarter(starter())).toBe(true);
    expect(isStarter({ ...starter(), preset: "some-other-preset" })).toBe(false);
    expect(isStarter({ ...starter(), named: true })).toBe(false);
    expect(isStarter({ ...starter(), decisions: { policy: "rules", control: "gate" } })).toBe(false);
  });
});
