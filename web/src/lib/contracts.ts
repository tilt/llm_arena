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
  Leaderboard?: Leaderboard;
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
  TaskView?: TaskView;
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
  configs?: PipelineConfig[];
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
  /**
   * presets defined in the experiment itself (override the runtime's)
   */
  presets?: {
    [k: string]: ModelPreset | undefined;
  };
  repeats?: number;
  scenarios: string[];
  seed?: number;
  /**
   * tasks of this split only (tasks without a split are always included)
   */
  split?: "all" | "dev" | "test";
  /**
   * replacement study: baseline + one config per swapped role and candidate model
   */
  study?: StudyConfig | null;
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
   * model preset: roles not bound explicitly run on its model for their kind
   */
  preset?: string | null;
  /**
   * role -> model alias or 'provider:model'
   */
  roles?: {
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
   * scenario -> role -> model: per-scenario bindings that override `roles`
   */
  scenario_roles?: {
    [k: string]:
      | {
          [k: string]: string | undefined;
        }
      | undefined;
  };
  /**
   * restrict to these scenarios
   */
  scenarios?: string[] | null;
  /**
   * set on configurations generated by a replacement study
   */
  study?: StudyTag | null;
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
  fallback?: ("llm" | "jev" | "ollaya") | null;
  /**
   * cascade: the scenario's rules answer first where they apply
   */
  hard_rules?: boolean;
  jev_model?: string;
  /**
   * decision model served by the local Ollaya app
   */
  ollaya_model?: string;
  policy?: "llm" | "rules" | "cascade" | "jev" | "ollaya";
  /**
   * cascade: first stage
   */
  primary?: "llm" | "jev" | "ollaya";
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
 * Marks a configuration generated by a study, so the report can compare it with the baseline.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "StudyTag".
 */
export interface StudyTag {
  candidate?: string | null;
  kind: "baseline" | "swap";
  role?: string | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ModelPreset".
 */
export interface ModelPreset {
  /**
   * 'ollaya:<model>' or 'jev:<model>': the dedicated decision model, if any
   */
  decision_service?: string | null;
  description?: string;
  label: string;
  /**
   * step kind -> model reference
   */
  models: {
    [k: string]: string | undefined;
  };
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "StudyConfig".
 */
export interface StudyConfig {
  /**
   * the preset every configuration starts from (the baseline)
   */
  baseline: string;
  /**
   * model references (or ollaya:/jev: decision models) to try
   *
   * @minItems 1
   */
  candidates: [string, ...string[]];
  /**
   * how a decision-service candidate controls the agent
   */
  decision_control?: "gate" | "policy" | "review";
  /**
   * roles to swap (default: every role except the decision roles)
   */
  roles?: string[] | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Leaderboard".
 */
export interface Leaderboard {
  entries: LeaderboardEntry[];
  scenario: string;
  scenario_version: string;
  /**
   * distinct tasks run by any entry
   */
  tasks: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "LeaderboardEntry".
 */
export interface LeaderboardEntry {
  ci_high: number;
  ci_low: number;
  /**
   * name of the config in its latest run
   */
  config: string;
  /**
   * pass-rate difference on the shared tasks
   */
  delta_vs_leader?: number | null;
  fingerprint: string;
  latency_p50_s: number;
  mean_cost_usd: number;
  mean_tokens: number;
  /**
   * every name this setup ran under
   */
  names: string[];
  /**
   * paired permutation test on the shared tasks
   */
  p_vs_leader?: number | null;
  /**
   * mean over tasks of the per-task pass share
   */
  pass_rate: number;
  rank: number;
  /**
   * every trial, by task, then run and repeat
   */
  results?: TrialResult[];
  runs: string[];
  /**
   * ranking score: pass rate adjusted for the number of tasks, (passes + 1) / (tasks + 2)
   */
  score?: number;
  /**
   * roles (model + call settings), params and control policy
   */
  setup: {
    [k: string]: unknown | undefined;
  };
  /**
   * tasks shared with the leader
   */
  shared_tasks?: number | null;
  tasks: number;
  trials: number;
}
/**
 * One trial behind an entry, so a leaderboard can link straight into its run and step inspector.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "TrialResult".
 */
export interface TrialResult {
  passed: boolean;
  repeat: number;
  run_id: string;
  status: string;
  task_id: string;
  trial_id: string;
}
/**
 * Everything the report viewer needs for one run; export/import format between runtimes.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunBundle".
 */
export interface RunBundle {
  /**
   * artifact key -> file, for the included traces (exports, browser storage)
   */
  artifacts?: {
    [k: string]: BundledArtifact | undefined;
  };
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
  /**
   * trial id -> trace (empty when loaded lazily)
   */
  traces?: {
    [k: string]: unknown | undefined;
  };
  trials: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "BundledArtifact".
 */
export interface BundledArtifact {
  /**
   * base64
   */
  data: string;
  media_type: string;
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
  /**
   * replacement studies: each swapped step against the baseline
   */
  replacements?: ReplacementEffect[];
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
 * One swapped step against the baseline, on the tasks both ran (replacement studies).
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ReplacementEffect".
 */
export interface ReplacementEffect {
  baseline_rate: number;
  candidate: string;
  config: string;
  delta: number;
  delta_cost_usd: number;
  delta_latency_s: number;
  errors?: number;
  p_value: number;
  role: string;
  scenario: string;
  step_deltas?: {
    [k: string]: number | undefined;
  };
  tasks: number;
  variant_rate: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunStarted".
 */
export interface RunStarted {
  pending: number;
  run_id: string;
  /**
   * unix time
   */
  started_at?: number;
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
  /**
   * live runs: trials done, running, queued, spend
   */
  progress?: RunProgress | null;
  run_id: string;
  scenarios?: string[];
  trials: number;
}
/**
 * Where a live run stands, from its events (the Runs list and the navigation badge show it).
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunProgress".
 */
export interface RunProgress {
  done: number;
  errors: number;
  finished?: boolean;
  passed: number;
  queued: number;
  running: number;
  spent_usd: number;
  /**
   * unix time
   */
  started_at?: number | null;
  /**
   * trials to run in this session (finished ones of a resumed run excluded)
   */
  total: number;
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
   * 'jev' / 'ollaya' -> availability and models (System One decision models)
   */
  decision_services?: {
    [k: string]: DecisionServiceInfo | undefined;
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
  /**
   * container | process | browser worker ('' without one)
   */
  sandbox_isolation?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "DecisionServiceInfo".
 */
export interface DecisionServiceInfo {
  models?: string[];
  /**
   * 'available' or why not
   */
  status: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RuntimeResponse".
 */
export interface RuntimeResponse {
  /**
   * 'jev' / 'ollaya' -> availability and models (System One decision models)
   */
  decision_services?: {
    [k: string]: DecisionServiceInfo | undefined;
  };
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
  /**
   * container | process | browser worker ('' without one)
   */
  sandbox_isolation?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ScenarioManifest".
 */
export interface ScenarioManifest {
  /**
   * what the scenario tests and how it is graded
   */
  brief?: Brief | null;
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
  /**
   * bumped when prompts, tools or evaluators change
   */
  version?: string;
  wiki?: WikiLink[];
  /**
   * steps, transitions and the role running each step
   */
  workflow?: Workflow | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Brief".
 */
export interface Brief {
  /**
   * useful ablations (parameters to vary)
   */
  compare?: string[];
  /**
   * pass criterion -> what it checks, in plain words
   */
  criteria: {
    [k: string]: string | undefined;
  };
  /**
   * what the agent works with
   */
  environment: string;
  /**
   * step-level measurements worth knowing
   */
  measured?: string[];
  /**
   * what the scenario tests, in one or two sentences
   */
  summary: string;
  /**
   * what makes the tasks hard
   */
  traps?: string[];
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
  /**
   * what the role does, for baseline profiles: text, vision, code, agent, decision
   */
  kind?: "text" | "vision" | "code" | "agent" | "decision";
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
 * via the `definition` "Workflow".
 */
export interface Workflow {
  edges: WorkflowEdge[];
  steps: WorkflowStep[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "WorkflowEdge".
 */
export interface WorkflowEdge {
  label?: string;
  /**
   * goes back to an earlier step (drawn as a return arc)
   */
  loop?: boolean;
  source: string;
  target: string;
  /**
   * dropped when this step is part of the resolved workflow
   */
  unless?: string | null;
  when?: Condition[];
}
/**
 * True when the parameter matches: `equals` / `one_of` / `gt` (all given ones must hold).
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Condition".
 */
export interface Condition {
  equals?: {
    [k: string]: unknown | undefined;
  };
  gt?: number | null;
  one_of?: unknown[] | null;
  param: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "WorkflowStep".
 */
export interface WorkflowStep {
  /**
   * further roles the step may call (e.g. a fallback)
   */
  also?: string[];
  description?: string;
  id: string;
  kind: "start" | "end" | "llm" | "tool" | "code" | "check" | "decision" | "human";
  label: string;
  /**
   * role whose model runs this step (model and decision steps)
   */
  role?: string | null;
  when?: Condition[];
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
 * via the `definition` "TaskView".
 */
export interface TaskView {
  expected: Expectation[];
  id: string;
  note?: string;
  prompt: string;
  split?: string | null;
  tags?: string[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Expectation".
 */
export interface Expectation {
  format?: "text" | "list" | "code" | "table" | "json";
  label: string;
  /**
   * for code: sql, python, …
   */
  language?: string | null;
  /**
   * text, list of strings, code, table rows (list of lists) or JSON
   */
  value: {
    [k: string]: unknown | undefined;
  };
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
  artifacts?: ArtifactRef[];
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
  step?: string | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ArtifactRef".
 */
export interface ArtifactRef {
  /**
   * store key (<trial>/<seq>-<name>); empty when not stored
   */
  key?: string;
  media_type: string;
  name: string;
  /**
   * why it was not stored, if it was not
   */
  note?: string;
  size: number;
}
