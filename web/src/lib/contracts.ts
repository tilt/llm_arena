/* Generated from contracts/schemas by `npm run contracts`. Do not edit. */

/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunEvent".
 */
export type RunEvent = RunStarted | TrialStarted | TrialFinished | BudgetExceeded | RunFinished;

export interface Contracts {
  CatalogEntry?: CatalogEntry;
  Estimate?: Estimate;
  ExperimentConfig?: ExperimentConfig;
  ModelSpec?: ModelSpec;
  RunBundle?: RunBundle;
  RunEvent?: RunEvent;
  RunListing?: RunListing;
  RunStartedResponse?: RunStartedResponse;
  RuntimeInfo?: RuntimeInfo;
  RuntimeResponse?: RuntimeResponse;
  ScenarioManifest?: ScenarioManifest;
  Score?: Score;
  SetKey?: SetKey;
  StartRun?: StartRun;
  Task?: Task;
  Trace?: Trace;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CatalogEntry".
 */
export interface CatalogEntry {
  context_length?: number | null;
  input_cost_per_mtok?: number | null;
  loaded?: boolean | null;
  output_cost_per_mtok?: number | null;
  parameters?: string | null;
  quantization?: string | null;
  size_gb?: number | null;
  snapshot?: boolean;
  source: "ollama" | "lmstudio" | "openai" | "anthropic";
  spec: ModelSpec;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ModelSpec".
 */
export interface ModelSpec {
  api_key_env?: string | null;
  backend?: "auto" | "openai" | "anthropic" | "http" | "aisuite";
  base_url?: string | null;
  capabilities?: Capabilities;
  concurrency?: number | null;
  extra_body?: {
    [k: string]: unknown | undefined;
  };
  input_cost_per_mtok?: number | null;
  max_retries?: number;
  max_tokens?: number | null;
  /**
   * Model id as the server knows it
   */
  model: string;
  /**
   * Arena-wide alias, e.g. 'qwen3-14b@lmstudio'
   */
  name: string;
  output_cost_per_mtok?: number | null;
  provider: "openai" | "anthropic" | "ollama" | "lmstudio" | "openai_compatible";
  reasoning_effort?: ("none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max") | null;
  temperature?: number | null;
  timeout_s?: number;
  tool_mode?: "native" | "json";
}
/**
 * What a model can do; checked before a run so a bad role binding fails fast.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Capabilities".
 */
export interface Capabilities {
  json_schema?: boolean;
  reasoning?: boolean;
  tools?: boolean;
  vision?: boolean;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Estimate".
 */
export interface Estimate {
  cost_usd: number;
  note?: string;
  per_scenario: {
    [k: string]: number | undefined;
  };
  tokens: number;
  trials: number;
  /**
   * models without a known price (costed at 0)
   */
  unknown_prices?: string[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ExperimentConfig".
 */
export interface ExperimentConfig {
  arena?: ArenaConfig;
  configs: PipelineConfig[];
  judge?: string | null;
  /**
   * max tasks per scenario
   */
  limit?: number | null;
  /**
   * stop the run once model spend reaches this limit
   */
  max_cost_usd?: number | null;
  max_parallel_trials?: number;
  models_file?: string;
  name: string;
  repeats?: number;
  scenarios: string[];
  seed?: number;
  /**
   * tasks of this split only (tasks without a split are always included)
   */
  split?: "all" | "dev" | "test";
  task_ids?: string[] | null;
  trial_timeout_s?: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ArenaConfig".
 */
export interface ArenaConfig {
  enabled?: boolean;
  judge?: string | null;
  max_pairs_per_task?: number;
}
/**
 * One contestant: a name, a role → model binding, and pattern parameters.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PipelineConfig".
 */
export interface PipelineConfig {
  /**
   * control policy for scenarios that support one; None: the agent decides
   */
  decisions?: DecisionConfig | null;
  name: string;
  /**
   * pattern params, applied to every scenario that knows the key
   */
  params?: {
    [k: string]: unknown | undefined;
  };
  /**
   * role -> model alias or 'provider:model'
   */
  roles: {
    [k: string]: string | undefined;
  };
  /**
   * per-scenario overrides
   */
  scenario_params?: {
    [k: string]:
      | {
          [k: string]: unknown | undefined;
        }
      | undefined;
  };
  /**
   * restrict to these scenarios
   */
  scenarios?: string[] | null;
}
/**
 * Control policy of a pipeline config. Without it the agent decides everything inside its own loop.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "DecisionConfig".
 */
export interface DecisionConfig {
  /**
   * policy: the policy picks each next tool, judges completion and gates state-changing actions; gate: the agent loop runs as usual and the policy only gates state-changing actions; review: the agent runs unchanged and the policy only reviews the finished trace
   */
  control?: "policy" | "gate" | "review";
  /**
   * cascade: stage for uncertain answers (None: no stage)
   */
  fallback?: ("llm" | "jev") | null;
  /**
   * cascade: the scenario's rules answer first where they apply
   */
  hard_rules?: boolean;
  jev_model?: string;
  policy?: "llm" | "rules" | "cascade" | "jev";
  /**
   * cascade: first stage
   */
  primary?: "llm" | "jev";
  /**
   * classify the finished trace (task done? needs human review?)
   */
  review?: boolean;
  /**
   * cascade: escalate below this confidence
   */
  threshold?: number;
  /**
   * per-question thresholds
   */
  thresholds?: {
    [k: string]: number | undefined;
  };
}
/**
 * Everything the report viewer needs for one run; export/import format between runtimes.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunBundle".
 */
export interface RunBundle {
  battles: {
    [k: string]: unknown | undefined;
  }[];
  /**
   * one row per control decision × question
   */
  decisions?: {
    [k: string]: unknown | undefined;
  }[];
  run: {
    [k: string]: unknown | undefined;
  };
  scores: {
    [k: string]: unknown | undefined;
  }[];
  summary: BundleSummary;
  traces: {
    [k: string]: unknown | undefined;
  };
  trials: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "BundleSummary".
 */
export interface BundleSummary {
  configs: ConfigSummary[];
  /**
   * control-policy decision quality
   */
  decisions?: DecisionSummary[];
  paired_tests: PairedTest[];
  /**
   * scope ('overall' or scenario) -> config -> rating
   */
  ratings: {
    [k: string]:
      | {
          [k: string]: number | undefined;
        }
      | undefined;
  };
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ConfigSummary".
 */
export interface ConfigSummary {
  ci_high: number;
  ci_low: number;
  config: string;
  derived?: {
    [k: string]: number | undefined;
  };
  e2e_means?: {
    [k: string]: number | undefined;
  };
  errors: number;
  judge_cost_usd: number;
  latency_p50_s: number;
  latency_p95_s: number;
  mean_cost_usd: number;
  mean_tokens: number;
  pass_at_k: number;
  pass_hat_k: number;
  pass_rate: number;
  pattern: string;
  per_task_pass?: {
    [k: string]: number | undefined;
  };
  repeats: number;
  roles: {
    [k: string]: string | undefined;
  };
  scenario: string;
  step_means?: {
    [k: string]: number | undefined;
  };
  tasks: number;
  trials: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "DecisionSummary".
 */
export interface DecisionSummary {
  abstain_rate: number;
  accuracy: number | null;
  brier: number | null;
  calibration?: CalibrationBin[];
  config: string;
  cost_usd: number;
  escalation_rate: number;
  /**
   * noul: P(pred true | label false); approval: unnecessary escalations
   */
  false_alarm_rate: number | null;
  human_reviews: number;
  labeled: number;
  latency_p50_s: number;
  latency_p95_s: number;
  log_loss: number | null;
  /**
   * noul: P(pred false | label true); approval/review: false-safe
   */
  missed_rate: number | null;
  n: number;
  point: string;
  policy: string;
  qtype: string;
  question: string;
  scenario: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CalibrationBin".
 */
export interface CalibrationBin {
  high: number;
  low: number;
  /**
   * mean predicted P(true)
   */
  mean_p: number;
  n: number;
  /**
   * share of true labels
   */
  observed: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PairedTest".
 */
export interface PairedTest {
  best: string;
  difference: number;
  other: string;
  p_value: number;
  scenario: string;
  tasks: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunStarted".
 */
export interface RunStarted {
  pending: number;
  run_id: string;
  total: number;
  type?: "run_started";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "TrialStarted".
 */
export interface TrialStarted {
  config: string;
  repeat: number;
  scenario: string;
  task_id: string;
  trial_id: string;
  type?: "trial_started";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "TrialFinished".
 */
export interface TrialFinished {
  config: string;
  cost_usd: number;
  done: number;
  duration_s: number;
  passed: boolean;
  repeat: number;
  scenario: string;
  status: string;
  task_id: string;
  total: number;
  trial_id: string;
  type?: "trial_finished";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "BudgetExceeded".
 */
export interface BudgetExceeded {
  limit_usd: number;
  spent_usd: number;
  type?: "budget_exceeded";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunFinished".
 */
export interface RunFinished {
  run_id: string;
  spent_usd: number;
  stopped_early: boolean;
  type?: "run_finished";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunListing".
 */
export interface RunListing {
  active: boolean;
  created_at: string;
  errors: number;
  name: string;
  passed: number;
  run_id: string;
  trials: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunStartedResponse".
 */
export interface RunStartedResponse {
  run_id: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RuntimeInfo".
 */
export interface RuntimeInfo {
  /**
   * TypeSafe's Jev decision model: 'available' or why not
   */
  jev?: string;
  live_search: boolean;
  /**
   * provider -> 'available' or why not (never key material)
   */
  providers: {
    [k: string]: string | undefined;
  };
  runtime: string;
  sandbox: boolean;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RuntimeResponse".
 */
export interface RuntimeResponse {
  /**
   * TypeSafe's Jev decision model: 'available' or why not
   */
  jev?: string;
  keys: {
    [k: string]: "env" | "session" | "missing" | undefined;
  };
  live_search: boolean;
  /**
   * provider -> 'available' or why not (never key material)
   */
  providers: {
    [k: string]: string | undefined;
  };
  runtime: string;
  sandbox: boolean;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ScenarioManifest".
 */
export interface ScenarioManifest {
  description: string;
  id: string;
  kind: "pattern" | "benchmark";
  open_ended?: boolean;
  params: ParamManifest[];
  pass_criteria: string[];
  pattern: string;
  requires?: ("sandbox" | "live_network" | "local_models")[];
  roles: RoleManifest[];
  /**
   * accepts a control policy (config.decisions)
   */
  supports_decisions?: boolean;
  tasks: number;
  title: string;
  wiki?: WikiLink[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ParamManifest".
 */
export interface ParamManifest {
  choices?: unknown[] | null;
  default: unknown;
  description?: string;
  name: string;
  type: "integer" | "number" | "boolean" | "string";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RoleManifest".
 */
export interface RoleManifest {
  description: string;
  /**
   * optional role: reuses this role's model when unbound
   */
  fallback?: string | null;
  name: string;
  /**
   * capabilities the bound model must have
   */
  needs?: string[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "WikiLink".
 */
export interface WikiLink {
  title: string;
  url: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Score".
 */
export interface Score {
  level: "step" | "e2e";
  name: string;
  passed?: boolean | null;
  rationale?: string;
  value: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "SetKey".
 */
export interface SetKey {
  key: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "StartRun".
 */
export interface StartRun {
  experiment: ExperimentConfig;
  live?: boolean;
  run_id?: string | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Task".
 */
export interface Task {
  data?: {
    [k: string]: unknown | undefined;
  };
  id: string;
  prompt: string;
  tags?: string[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Trace".
 */
export interface Trace {
  spans?: Span[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Span".
 */
export interface Span {
  attrs?: {
    [k: string]: unknown | undefined;
  };
  completion_tokens?: number;
  cost_usd?: number;
  duration_s?: number;
  error?: string | null;
  input?: {
    [k: string]: unknown | undefined;
  };
  kind: "llm_call" | "tool_call" | "code_exec" | "handoff" | "plan" | "critique" | "step" | "judge" | "decision";
  model?: string | null;
  name: string;
  output?: {
    [k: string]: unknown | undefined;
  };
  parent?: number | null;
  prompt_tokens?: number;
  role?: string | null;
  started_at?: number;
}
