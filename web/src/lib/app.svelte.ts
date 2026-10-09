// Shared app state: the detected backend plus data every view needs.
import { untrack } from "svelte";
import type { ArenaBackend, ModelsResponse } from "./backend";
import { activePreset, setActivePreset, startPreset } from "./presets";
import { adoptStartPreset, draft } from "./draft.svelte";
import type { ModelPreset, RuntimeResponse, ScenarioManifest } from "./contracts";

export const app = $state({
  backend: null as ArenaBackend | null,
  mode: "detecting" as "detecting" | "local" | "browser" | "locked",
  runtime: null as RuntimeResponse | null,
  scenarios: [] as ScenarioManifest[],
  models: null as ModelsResponse | null,
  presets: {} as Record<string, ModelPreset>,
  /** the preset the user chose for new setups (kept in this browser); startHere() says which one they actually use */
  activePreset: activePreset(),
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
    app.scenarios = scenarios;
    app.models = models;
    app.error = "";
  } catch (error) {
    app.error = error instanceof Error ? error.message : String(error);
  }
}

/** Choose the preset new setups start from (the Presets page). */
export function chooseActivePreset(name: string): void {
  app.activePreset = name;
  setActivePreset(name);
}

/** The preset new setups start from right now: the chosen one if its models all run here (no Ollama, no OpenAI key
 *  and it does not), else the first that does, else none (""). Never stored, so it follows models, presets and the
 *  choice; read it in an effect or a derived to stay in step. The chosen one stays the user's preference. */
export function startHere(): string {
  return app.models ? startPreset(app.presets, app.models, app.activePreset) : "";
}

// The one update path for untouched starters: whenever the start preset changes (models loaded or refreshed, a preset
// saved, reset or deleted, another one chosen), they follow it. Setups the user chose in stay as they are.
$effect.root(() => {
  $effect(() => {
    const start = startHere();
    if (app.models) untrack(() => adoptStartPreset(draft.configs, start));
  });
});
