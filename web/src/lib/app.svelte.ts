// Shared app state: the detected backend plus data every view needs.
import type { ArenaBackend, ModelsResponse } from "./backend";
import type { RuntimeResponse, ScenarioManifest } from "./contracts";

export const app = $state({
  backend: null as ArenaBackend | null,
  mode: "detecting" as "detecting" | "local" | "browser",
  runtime: null as RuntimeResponse | null,
  scenarios: [] as ScenarioManifest[],
  models: null as ModelsResponse | null,
  error: "",
  status: "",
});

export async function refresh(options: { models?: boolean } = {}): Promise<void> {
  const backend = app.backend;
  if (!backend) return;
  try {
    const [runtime, scenarios, models] = await Promise.all([
      backend.runtime(),
      app.scenarios.length ? Promise.resolve(app.scenarios) : backend.scenarios(),
      backend.models(options.models ?? false),
    ]);
    app.runtime = runtime;
    app.scenarios = scenarios;
    app.models = models;
    app.error = "";
  } catch (error) {
    app.error = error instanceof Error ? error.message : String(error);
  }
}
