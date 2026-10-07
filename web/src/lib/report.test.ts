import { expect, it } from "vitest";

import type { ConfigSummary, RunBundle } from "./contracts";
import { passRateMatrix, ratings, sections, stepMatrix } from "./report";

const config = (scenario: string, name: string, rate: number, steps: Record<string, number>): ConfigSummary => ({
  scenario, config: name, pattern: "reflection", pass_rate: rate, ci_low: 0, ci_high: 1, credit: rate, pass_hat_k: rate, pass_at_k: rate,
  trials: 2, tasks: 1, repeats: 2, errors: 0, mean_tokens: 100, mean_cost_usd: 0, judge_cost_usd: 0, latency_p50_s: 1,
  latency_p95_s: 2, roles: {}, step_means: steps, e2e_means: { final_correct: rate }, derived: {}, per_task_pass: {},
});

const bundle = {
  run: {}, trials: [], scores: [], battles: [], traces: {},
  summary: {
    configs: [config("sql", "a", 0.5, { draft_correct: 0.5, sql_attempts: 1.5 }), config("sql", "b", 1, { draft_correct: 1, sql_attempts: 1 }),
              config("email", "a", 0.2, {})],
    paired_tests: [{ scenario: "sql", best: "b", other: "a", difference: 0.5, p_value: 0.3, tasks: 1 }],
    ratings: { sql: { a: 990, b: 1010 }, overall: { a: 995, b: 1005 } },
  },
} as unknown as RunBundle;

it("groups configs per scenario, best first, and keeps only rates in the step heatmap", () => {
  const [email, sql] = sections(bundle);
  expect(email!.scenario).toBe("email");
  expect(sql!.configs.map((c) => c.config)).toEqual(["b", "a"]);
  expect(sql!.stepMetrics).toEqual(["draft_correct", "sql_attempts"]);
  expect(stepMatrix(sql!)).toEqual({ rows: ["b", "a"], columns: ["draft_correct"], values: [[1], [0.5]] });
  expect(sql!.tests).toHaveLength(1);
});

it("builds the overview matrix with gaps and ranks ratings with overall first", () => {
  expect(passRateMatrix(bundle)).toEqual({ rows: ["a", "b"], columns: ["email", "sql"], values: [[0.2, 0.5], [null, 1]] });
  expect(ratings(bundle).map((r) => [r.scope, r.ranking[0]![0]])).toEqual([["overall", "b"], ["sql", "b"]]);
});
