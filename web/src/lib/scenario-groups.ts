// Curated suites: what to run (scenarios, method variants, run settings). Each one mirrors a CLI experiment in
// configs/experiments (scenario-groups.test.ts keeps them in step); the models are the user's own bundles instead of
// the YAML's fixed ones.
import { activePreset, usableActive } from "./presets";
import { configForPreset, type BuilderState, type StudyDraft, type VariantDraft } from "./builder";
import type { DecisionConfig, ModelPreset, ScenarioManifest } from "./contracts";

export type SuiteKind = "compare" | "study";

/** One way of running a suite's scenarios: parameters or a control policy changed (every model bundle runs it). */
export interface SuiteVariant {
  name: string;
  decisions?: DecisionConfig;
  /** applied to every selected scenario that has the parameter */
  params?: Record<string, unknown>;
}

export interface ScenarioSuite {
  id: string;
  title: string;
  description: string;
  kind: SuiteKind;
  /** the CLI experiment this suite mirrors, relative to the repository root */
  cli: string;
  scenarioIds?: string[];
  scenarioKind?: ScenarioManifest["kind"];
  limit: number | null;
  repeats: number;
  split?: BuilderState["split"];
  judge?: string;
  arena?: boolean;
  maxCostUsd?: number;
  /** method variants to compare; default: one plain run */
  variants?: SuiteVariant[];
  study?: Partial<StudyDraft>;
}

export const SUITES: ScenarioSuite[] = [
  {
    id: "smoke",
    title: "Smoke check",
    description: "A quick end-to-end run: one reflection scenario and one tool-use scenario, 3 tasks each.",
    kind: "compare",
    cli: "configs/experiments/smoke.yaml",
    scenarioIds: ["reflection_sql", "email_assistant"],
    limit: 3,
    repeats: 1,
    maxCostUsd: 1,
  },
  {
    id: "workflow_agents",
    title: "Workflow agents",
    description: "Every agentic-pattern scenario: tools, planning, ReAct, code execution, reports and charts.",
    kind: "compare",
    cli: "configs/experiments/agentic.yaml",
    scenarioIds: ["email_assistant", "react_multihop", "research_report", "shop_codeact", "trip_planner", "launch_brief", "chart_codegen"],
    limit: null,
    repeats: 2,
    judge: "judge-gpt-4.1-mini",
    arena: true,
    maxCostUsd: 3,
  },
  {
    id: "classic_benchmarks",
    title: "Classic benchmarks",
    description: "GSM8K, MMLU-Pro, IFEval, coding and function-calling subsets, 30 tasks each.",
    kind: "compare",
    cli: "configs/experiments/benchmarks.yaml",
    scenarioKind: "benchmark",
    limit: 30,
    repeats: 1,
    maxCostUsd: 2,
  },
  {
    id: "reflection",
    title: "Reflection",
    description: "SQL and writing tasks, each run without and with a self-reflection round.",
    kind: "compare",
    cli: "configs/experiments/reflection.yaml",
    scenarioIds: ["reflection_sql", "reflection_writing"],
    limit: null,
    repeats: 3,
    judge: "judge-gpt-4.1-mini",
    arena: true,
    maxCostUsd: 2,
    variants: [{ name: "no-reflection", params: { reflection_rounds: 0 } }, { name: "self-reflect" }],
  },
  {
    id: "decision_policies",
    title: "Decision policies",
    description: "Who makes the agent's control decisions: the agent itself, a rules gate, an LLM gate or an LLM controller. Dev split.",
    kind: "compare",
    cli: "configs/experiments/decisions.yaml",
    scenarioIds: ["support_desk", "email_assistant"],
    limit: null,
    repeats: 2,
    split: "dev",
    maxCostUsd: 2,
    variants: [
      { name: "agent-decides" },
      { name: "rules-gate", decisions: { policy: "rules", control: "gate" } },
      { name: "llm-gate", decisions: { policy: "llm", control: "gate" } },
      { name: "llm-controls", decisions: { policy: "llm", control: "policy" } },
    ],
  },
  {
    id: "critic_study",
    title: "Critic replacement study",
    description: "Start from a preset and measure what a stronger critic model changes.",
    kind: "study",
    cli: "configs/experiments/replacement-study.yaml",
    scenarioIds: ["reflection_sql", "chart_codegen"],
    limit: 3,
    repeats: 1,
    maxCostUsd: 2,
    study: { roles: ["critic"] },
  },
];

export const suiteScenarios = (suite: ScenarioSuite, manifests: ScenarioManifest[]): string[] => {
  if (suite.scenarioKind) return manifests.filter((m) => m.kind === suite.scenarioKind).map((m) => m.id);
  const available = new Set(manifests.map((m) => m.id));
  return (suite.scenarioIds ?? []).filter((id) => available.has(id));
};

const variantDraft = (variant: SuiteVariant): VariantDraft => ({
  name: variant.name, params: { ...(variant.params ?? {}) }, decisions: variant.decisions ? { threshold: 0.8, ...variant.decisions } : null,
});

/** Fill in what to run from the suite: scenarios, variants and run settings. The model bundles are the user's and
 *  stay; a replacement study takes the first bundle's preset (or the usable one) as its baseline. */
export function applySuite(
  state: BuilderState, suite: ScenarioSuite, manifests: ScenarioManifest[], profiles: Record<string, ModelPreset> = {},
): void {
  const preset = usableActive(profiles) || activePreset();
  state.suite = suite.id;
  state.name = suite.id.replace(/_/g, "-");
  state.scenarios = suiteScenarios(suite, manifests);
  state.variants = (suite.variants ?? []).map(variantDraft);
  state.repeats = suite.repeats;
  state.limit = suite.limit;
  state.judge = suite.judge ?? "";
  state.arena = Boolean(suite.arena);
  state.maxCostUsd = suite.maxCostUsd ?? 1;
  state.budgetMode = "best_effort";
  state.split = suite.split ?? "all";
  if (!state.configs.length) state.configs = [configForPreset(preset)];
  const baseline = state.configs.map((c) => c.preset ?? "").find((p) => p && profiles[p]) || preset;
  state.study = suite.kind === "study"
    ? { baseline, candidates: [""], roles: suite.study?.roles ?? [], decisionControl: suite.study?.decisionControl ?? "gate" }
    : null;
}

/** Clear what a suite filled in; the model bundles stay. */
export function clearSuite(state: BuilderState): void {
  state.suite = "";
  state.name = "my-experiment";
  state.scenarios = [];
  state.variants = [];
  state.repeats = 1;
  state.limit = 3;
  state.judge = "";
  state.arena = false;
  state.maxCostUsd = 1;
  state.budgetMode = "best_effort";
  state.split = "all";
  state.study = null;
}

/** What the draft changed of its suite's "what to run" (scenarios, variants, run settings); empty = as the suite. */
export function suiteChanges(state: BuilderState, suite: ScenarioSuite, manifests: ScenarioManifest[]): string[] {
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const scenarios = suiteScenarios(suite, manifests);
  const changes = [
    !same([...state.scenarios].sort(), [...scenarios].sort()) && "scenarios",
    !same(state.variants ?? [], (suite.variants ?? []).map(variantDraft)) && "variants",
    (state.limit !== suite.limit || state.repeats !== suite.repeats || state.split !== (suite.split ?? "all")
      || state.judge !== (suite.judge ?? "") || state.arena !== Boolean(suite.arena)) && "run settings",
    (suite.kind === "study") !== Boolean(state.study) && "mode",
  ];
  return changes.filter((c): c is string => Boolean(c));
}
