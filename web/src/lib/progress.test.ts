import { expect, it } from "vitest";

import type { RunEvent } from "./contracts";
import { initialProgress, reduce } from "./progress";

it("folds run events into progress", () => {
  const trial = { trial_id: "t", scenario: "s", config: "c", task_id: "k", repeat: 0 };
  const events: RunEvent[] = [
    { type: "run_started", run_id: "r", total: 3, pending: 2 },
    { type: "trial_started", ...trial },
    { type: "trial_finished", ...trial, status: "ok", passed: true, duration_s: 1, cost_usd: 0.1, done: 1, total: 2 },
    { type: "trial_started", ...trial, trial_id: "u", task_id: "j" },
    { type: "trial_finished", ...trial, trial_id: "u", task_id: "j", status: "error", passed: false, duration_s: 1, cost_usd: 0.2, done: 2, total: 2 },
    { type: "budget_exceeded", spent_usd: 0.3, limit_usd: 0.25 },
    { type: "run_finished", run_id: "r", spent_usd: 0.3, stopped_early: true },
  ];
  const state = events.reduce(reduce, initialProgress);
  expect(state).toMatchObject({ total: 2, done: 2, passed: 1, failed: 0, errors: 1, finished: true, stoppedEarly: true, budgetHit: true, running: [] });
  expect(state.spentUsd).toBeCloseTo(0.3);
});
