import { describe, expect, it } from "vitest";

import type { TaskView } from "./contracts";
import { scenarioTasks } from "./tasks";

const task = (id: string): TaskView => ({ id, prompt: `prompt ${id}`, expected: [] });

describe("scenario tasks", () => {
  it("loads each scenario once per backend", async () => {
    const calls: string[] = [];
    const backend = { tasks: async (scenario: string) => { calls.push(scenario); return [task(`${scenario}-1`)]; } };
    expect((await scenarioTasks(backend, "sql"))[0]!.id).toBe("sql-1");
    await scenarioTasks(backend, "sql");
    await scenarioTasks(backend, "chart");
    expect(calls).toEqual(["sql", "chart"]);
    // Another backend (e.g. after switching runtime) loads its own.
    await scenarioTasks({ tasks: async () => { calls.push("other"); return []; } }, "sql");
    expect(calls).toEqual(["sql", "chart", "other"]);
  });

  it("retries after a failed load", async () => {
    let attempts = 0;
    const backend = { tasks: async () => { attempts += 1; if (attempts === 1) throw new Error("offline"); return [task("t")]; } };
    await expect(scenarioTasks(backend, "sql")).rejects.toThrow("offline");
    await Promise.resolve();
    expect(await scenarioTasks(backend, "sql")).toEqual([task("t")]);
    expect(attempts).toBe(2);
  });
});
