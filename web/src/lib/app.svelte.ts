// Shared app state: the detected backend plus data every view needs.
import type { ArenaBackend, ModelsResponse } from "./backend";
import { activePreset, setActivePreset, usableActive } from "./presets";
import { draft } from "./draft.svelte";
import type { ModelPreset, RuntimeResponse, ScenarioManifest } from "./contracts";

export const app = $state({
  backend: null as ArenaBackend | null,
  mode: "detecting" as "detecting" | "local" | "browser" | "locked",
  runtime: null as RuntimeResponse | null,
  scenarios: [] as ScenarioManifest[],
  models: null as ModelsResponse | null,
  presets: {} as Record<string, ModelPreset>,
  error: "",
  status: "",
  canRememberKeys: false,
  credentialNotice: "",
});

export async function refresh(options: { models?: boolean } = {}): Promise<void> {
  const backend = app.backend;
  if (!backend) return;
  try {
    const [runtime, scenarios, models, presets] = await Promise.all([
      backend.runtime(),
      app.scenarios.length ? Promise.resolve(app.scenarios) : backend.scenarios(),
      backend.models(options.models ?? false),
      backend.presets().catch(() => ({}) as Record<string, ModelPreset>),
    ]);
    app.runtime = runtime;
    app.presets = presets;
    // The active profile may not exist here (e.g. "Local small" in browser mode): fall back to a usable one.
    const usable = usableActive(presets);
    if (usable && usable !== activePreset()) setActivePreset(usable);
    for (const config of draft.configs) if (config.preset && !presets[config.preset]) config.preset = usable;
    if (draft.study && !presets[draft.study.baseline]) draft.study.baseline = usable;
    app.scenarios = scenarios;
    app.models = models;
    app.error = "";
  } catch (error) {
    app.error = error instanceof Error ? error.message : String(error);
  }
}
