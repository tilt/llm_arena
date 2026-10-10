/* Generated from contracts/schemas by `npm run contracts`. Do not edit. */

/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RunEvent".
 */
export type RunEvent = RunStarted | TrialStarted | TrialFinished | BudgetExceeded | RunWarning | RunFinished;

export interface Contracts {
  Candidate?: Candidate;
  CandidatesRequest?: CandidatesRequest;
  CatalogEntry?: CatalogEntry;
  Claim?: Claim;
  ClaimCheck?: ClaimCheck;
  ClaimDraft?: ClaimDraft;
  ClaimDraftRequest?: ClaimDraftRequest;
  ClaimExperimentRequest?: ClaimExperimentRequest;
  CreateClaimGist?: CreateClaimGist;
  CreatedGist?: CreatedGist;
  EndpointView?: EndpointView;
  Estimate?: Estimate;
  ExperimentConfig?: ExperimentConfig;
  GistClaim?: GistClaim;
  GistComment?: GistComment;
  Leaderboard?: Leaderboard;
  ModelSpec?: ModelSpec;
  PostComment?: PostComment;
  RenameRun?: RenameRun;
  Repro?: Repro;
  ReproDraft?: ReproDraft;
  ReproDraftRequest?: ReproDraftRequest;
  RunBundle?: RunBundle;
  RunEvent?: RunEvent;
  RunListing?: RunListing;
  RunStartedResponse?: RunStartedResponse;
  RuntimeInfo?: RuntimeInfo;
  RuntimeResponse?: RuntimeResponse;
  SaveEndpoint?: SaveEndpoint;
  ScenarioManifest?: ScenarioManifest;
  Score?: Score;
  SetKey?: SetKey;
  StartRun?: StartRun;
  Swap?: Swap;
  Task?: Task;
  TaskView?: TaskView;
  ThreadRequest?: ThreadRequest;
  Trace?: Trace;
  TrustStats?: TrustStats;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Candidate".
 */
export interface Candidate {
  /**
   * why it can't be this role's candidate (None: it can)
   */
  problem?: string | null;
  ref: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CandidatesRequest".
 */
export interface CandidatesRequest {
  claim: string;
  names?: {
    [k: string]: string | undefined;
  };
  role: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CatalogEntry".
 */
export interface CatalogEntry {
  context_length?: number | null;
  endpoint?: string | null;
  input_cost_per_mtok?: number | null;
  loaded?: boolean | null;
  output_cost_per_mtok?: number | null;
  parameters?: string | null;
  quantization?: string | null;
  size_gb?: number | null;
  snapshot?: boolean;
  source: "ollama" | "lmstudio" | "openai" | "anthropic" | "openai_compatible";
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
  endpoint?: string | null;
  endpoint_identity?: string | null;
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
 * via the `definition` "Claim".
 */
export interface Claim {
  arena_claim: 1;
  arena_version: string;
  /**
   * the LLM judge that graded it; None: code checks only
   */
  judge?: ClaimRole | null;
  made_at: string;
  parent_claim_hash?: string | null;
  repeats: number;
  result: ClaimResult;
  scenario: string;
  scenario_version: string;
  seed: number;
  setup: ClaimSetup;
  setup_fp: string;
  task_fps_hash: string;
  /**
   * @minItems 1
   * @maxItems 500
   */
  tasks: [ClaimTask, ...ClaimTask[]];
}
/**
 * A role's model as it travels: the call settings of `runner.fingerprint.SPEC_FIELDS`, no endpoint fields.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimRole".
 */
export interface ClaimRole {
  backend?: "auto";
  max_tokens?: number | null;
  /**
   * the provider's model id, or a self-hosted model's declared 'compare as' name
   */
  model: string;
  provider: "openai" | "anthropic" | "self_hosted";
  reasoning_effort?: ("none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max") | null;
  temperature?: number | null;
  tool_mode?: "native" | "json";
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimResult".
 */
export interface ClaimResult {
  /**
   * priced roles only
   */
  cost_usd_per_task: number;
  engine: "pages" | "local";
  partial: number;
  pass_rate: number;
  passed: number;
  trials: number;
  /**
   * roles whose cost is unknown
   *
   * @maxItems 16
   */
  unpriced_roles?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimSetup".
 */
export interface ClaimSetup {
  decisions?: {
    [k: string]: unknown | undefined;
  } | null;
  params?: {
    [k: string]: unknown | undefined;
  };
  roles: {
    [k: string]: ClaimRole | undefined;
  };
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimTask".
 */
export interface ClaimTask {
  fp: string;
  id: string;
}
/**
 * A loaded claim, after validation: the claim, its hash, whether it can be run here and now, and why not.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimCheck".
 */
export interface ClaimCheck {
  claim: Claim;
  claim_hash: string;
  message?: string;
  state: "ok" | "grading_drift" | "task_drift" | "newer_version";
  swappable_roles?: string[];
  uses_judge?: boolean;
}
/**
 * What Share as claim would publish (`claim_json`, its hash), or every reason it can't, in plain words.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimDraft".
 */
export interface ClaimDraft {
  claim_hash?: string | null;
  claim_json?: string | null;
  reasons?: string[];
  /**
   * local models that need a 'compare as' name
   */
  self_hosted?: string[];
}
/**
 * Share as claim: the "compare as" names for the run's self-hosted models; `config` picks one setup of a
 * Beat-this run (Share my variant).
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimDraftRequest".
 */
export interface ClaimDraftRequest {
  config?: string | null;
  names?: {
    [k: string]: string | undefined;
  };
}
/**
 * What Beat this runs: the claim, the visitor's own models for its self-hosted roles, an optional swap.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimExperimentRequest".
 */
export interface ClaimExperimentRequest {
  cap_usd?: number | null;
  claim: string;
  declared_names?: {
    [k: string]: string | undefined;
  };
  gist_id?: string | null;
  judge_local?: string | null;
  /**
   * role -> your model reference
   */
  local?: {
    [k: string]: string | undefined;
  };
  revision?: string | null;
  swap?: Swap | null;
}
/**
 * The visitor's one change: a role's model, or (local app) the control policy's decision service.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Swap".
 */
export interface Swap {
  /**
   * a model reference
   */
  candidate?: string | null;
  decisions?: {
    [k: string]: unknown | undefined;
  } | null;
  role?: string | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CreateClaimGist".
 */
export interface CreateClaimGist {
  claim: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CreatedGist".
 */
export interface CreatedGist {
  gist_id: string;
  html_url: string;
  owner: string;
  revision: string;
}
/**
 * An endpoint plus where its key comes from; never the key itself.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "EndpointView".
 */
export interface EndpointView {
  /**
   * env var holding the key (YAML only)
   */
  api_key_env?: string | null;
  /**
   * API root including the version, e.g. 'http://203.0.113.7:8000/v1'
   */
  base_url: string;
  capabilities?: Capabilities;
  concurrency?: number | null;
  id: string;
  input_cost_per_mtok?: number;
  key: "env" | "session" | "missing";
  output_cost_per_mtok?: number;
  /**
   * random, so the endpoint's identity (a keyed hash of its URL) cannot be reversed to the URL
   */
  salt?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Estimate".
 */
export interface Estimate {
  cost_usd: number;
  /**
   * something may cost money (a priced model or a paid decision service, which the estimate doesn't cost): a strict budget needs a limit
   */
  needs_cap?: boolean;
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
  budget_mode?: "best_effort" | "strict";
  /**
   * set on a run that reproduces a shared claim
   */
  claim_ref?: ClaimRef | null;
  /**
   * @maxItems 50
   */
  configs?: PipelineConfig[];
  judge?: string | null;
  /**
   * max tasks per scenario
   */
  limit?: number | null;
  /**
   * stop admitting calls near this best-effort spend limit
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
  /**
   * @maxItems 30
   */
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
 * Marks a run as a reproduction of a shared claim (see `llm_arena.claims`), so the run view can still post it
 * after a reload. Metadata only: fingerprints and resume keys never read it.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ClaimRef".
 */
export interface ClaimRef {
  claim_hash: string;
  /**
   * local self-hosted model ('<endpoint or provider>:<model>') -> the name it is compared as, frozen when the run started
   */
  declared_names?: {
    [k: string]: string | undefined;
  };
  /**
   * None for a hash-link claim
   */
  gist_id?: string | null;
  revision?: string | null;
}
/**
 * One contestant: a name, a role → model binding, and pattern parameters.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PipelineConfig".
 */
export interface PipelineConfig {
  /**
   * another configuration of the experiment, its baseline: the report shows the effect of what this one changes against it, on the tasks both ran
   */
  compare_to?: string | null;
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
   * marks a configuration that swaps one step's model (or a study's baseline): the report labels its effect by step and candidate model
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
   * @maxItems 200
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
 * A claim file at a pinned gist revision, with what the claim page shows around it.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "GistClaim".
 */
export interface GistClaim {
  claim: string;
  /**
   * how many comments the gist has (more than 300: the thread loads partially)
   */
  comments: number;
  /**
   * the gist's newest revision (differs: edited since the link was shared)
   */
  head_revision: string;
  html_url?: string;
  owner: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "GistComment".
 */
export interface GistComment {
  body: string;
  created_at: string;
  html_url?: string;
  id: number;
  updated_at: string;
  user: GistUser;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "GistUser".
 */
export interface GistUser {
  login: string;
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
   * partial credit: mean over tasks of the share of graded work done; breaks rank ties
   */
  credit?: number | null;
  /**
   * per pass criterion, in scenario order
   */
  criteria?: CriterionResult[];
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
 * One pass criterion of an entry: how often it passed and how much of it was met, both averaged over tasks
 * (errors and timeouts count as failed).
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "CriterionResult".
 */
export interface CriterionResult {
  credit: number;
  name: string;
  pass_rate: number;
}
/**
 * One trial behind an entry, so a leaderboard can link straight into its run and step inspector.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "TrialResult".
 */
export interface TrialResult {
  /**
   * partial credit: share of the graded work done
   */
  credit?: number | null;
  passed: boolean;
  repeat: number;
  run_id: string;
  status: string;
  task_id: string;
  trial_id: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PostComment".
 */
export interface PostComment {
  body: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "RenameRun".
 */
export interface RenameRun {
  /**
   * old setup name -> new setup name
   */
  configs?: {
    [k: string]: string | undefined;
  };
  /**
   * new display name of the run (None: unchanged)
   */
  name?: string | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Repro".
 */
export interface Repro {
  arena_repro: 1;
  arena_version: string;
  baseline: ReproSide;
  claim_hash: string;
  engine: "pages" | "local";
  judge?: ClaimRole | null;
  /**
   * @maxItems 500
   */
  per_task: PerTask[];
  scenario_version: string;
  /**
   * comment ids counted at post time
   *
   * @maxItems 300
   */
  seen?: number[];
  task_fps_hash: string;
  variant?: ReproVariant | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ReproSide".
 */
export interface ReproSide {
  budget_stopped: number;
  cost_usd_per_task: number;
  errors: number;
  passed: number;
  setup_fp: string;
  timeouts: number;
  trials: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PerTask".
 */
export interface PerTask {
  b: number;
  v?: number | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ReproVariant".
 */
export interface ReproVariant {
  budget_stopped: number;
  cost_usd_per_task: number;
  errors: number;
  passed: number;
  setup: ClaimSetup;
  setup_fp: string;
  timeouts: number;
  trials: number;
}
/**
 * The reproduction block a finished claim run would post, or why it can't be posted.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ReproDraft".
 */
export interface ReproDraft {
  block?: string | null;
  reasons?: string[];
  repro?: Repro | null;
  variant_config?: string | null;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ReproDraftRequest".
 */
export interface ReproDraftRequest {
  /**
   * the claim JSON
   */
  claim: string;
  /**
   * comment ids counted at post time
   *
   * @maxItems 300
   */
  seen?: number[];
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
   * each configuration with a compare_to against that baseline (replacements)
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
  credit: number | null;
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
  unpriced?: boolean;
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
 * One configuration against its baseline (its compare_to), on the tasks both ran. A replacement swaps one step:
 * role and candidate name it; both are empty for a configuration that changes something else.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ReplacementEffect".
 */
export interface ReplacementEffect {
  baseline?: string;
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
  unpriced?: boolean;
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
 * via the `definition` "RunWarning".
 */
export interface RunWarning {
  message: string;
  type?: "run_warning";
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
   * Docker only: 'rootless', 'root' (the daemon runs as root) or 'vm' (e.g. Docker Desktop)
   */
  sandbox_daemon?: string;
  /**
   * actionable setup help when code execution is unavailable
   */
  sandbox_hint?: string;
  /**
   * container | process | browser worker ('' without one)
   */
  sandbox_isolation?: string;
  /**
   * browser only: isolated | not network-isolated (empty for other runtimes)
   */
  sandbox_network_isolation?: string;
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
   * Docker only: 'rootless', 'root' (the daemon runs as root) or 'vm' (e.g. Docker Desktop)
   */
  sandbox_daemon?: string;
  /**
   * actionable setup help when code execution is unavailable
   */
  sandbox_hint?: string;
  /**
   * container | process | browser worker ('' without one)
   */
  sandbox_isolation?: string;
  /**
   * browser only: isolated | not network-isolated (empty for other runtimes)
   */
  sandbox_network_isolation?: string;
  /**
   * build id of the web UI when the server started ('' if none)
   */
  ui_build?: string;
}
/**
 * An endpoint as the app edits it. The id comes from the path; the key env var is not editable here, so a page
 * cannot point an existing key (say OPENAI_API_KEY) at a host of its choosing.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "SaveEndpoint".
 */
export interface SaveEndpoint {
  base_url: string;
  capabilities?: Capabilities;
  concurrency?: number | null;
  input_cost_per_mtok?: number;
  /**
   * optional; held in memory for this session only
   */
  key?: string | null;
  output_cost_per_mtok?: number;
  /**
   * keep the endpoint's identity (browser mode restores a remembered endpoint with it)
   */
  salt?: string | null;
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
 * via the `definition` "ThreadRequest".
 */
export interface ThreadRequest {
  author: string;
  claim: string;
  /**
   * @maxItems 300
   */
  comments?: {
    [k: string]: unknown | undefined;
  }[];
  engine?: ("pages" | "local") | null;
  total?: number | null;
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
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "TrustStats".
 */
export interface TrustStats {
  /**
   * claimed rate above the pooled interval (≥3 people)
   */
  above_interval?: boolean;
  /**
   * comments without a reproduction block
   */
  hidden: number;
  high?: number | null;
  loaded?: number;
  low?: number | null;
  /**
   * only the first `loaded` of `total` comments were read
   */
  partial?: boolean;
  passed?: number;
  /**
   * distinct non-author reproducers counted
   */
  people: number;
  rate?: number | null;
  /**
   * reproductions referenced by later ones but gone from the thread
   */
  removed?: number;
  rows: ThreadRow[];
  total?: number;
  trials?: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ThreadRow".
 */
export interface ThreadRow {
  baseline_cost_usd_per_task?: number;
  baseline_passed?: number;
  baseline_trials?: number;
  comment_id: number;
  created_at: string;
  engine?: ("pages" | "local") | null;
  reason?: string;
  status: "counted" | "author" | "superseded" | "rejected" | "edited" | "filtered";
  user: string;
  variant_cost_usd_per_task?: number | null;
  variant_model?: string | null;
  variant_passed?: number | null;
  variant_role?: string | null;
}
