// A scenario's tasks, loaded once per backend: the step inspector asks for them on every trial it opens, and a
// benchmark may first have to download its subset. A failed load is forgotten so the next view retries.
import type { ArenaBackend } from "./backend";
import type { TaskView } from "./contracts";

type TaskSource = Pick<ArenaBackend, "tasks">;

const cache = new WeakMap<TaskSource, Map<string, Promise<TaskView[]>>>();

export function scenarioTasks(backend: TaskSource, scenario: string): Promise<TaskView[]> {
  let byScenario = cache.get(backend);
  if (!byScenario) cache.set(backend, (byScenario = new Map()));
  let tasks = byScenario.get(scenario);
  if (!tasks) {
    const loading = backend.tasks(scenario);
    byScenario.set(scenario, loading);
    loading.catch(() => { if (byScenario.get(scenario) === loading) byScenario.delete(scenario); });
    tasks = loading;
  }
  return tasks;
}
