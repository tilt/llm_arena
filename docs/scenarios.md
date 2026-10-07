# Scenarios

All tasks, prompts, schemas and seed data are original and use fictional entities. Parameters can be overridden per
config with `params` or `scenario_params`.

## reflection_sql: reflection grounded in execution
- **Pipeline:** generator writes SQL → it is executed read-only → critic reviews the SQL and its result → generator
  revises.
- **Params:**
  - `reflection_rounds`.
  - `feedback`: `execution` or `sql_only`. Use this to measure what execution feedback adds.
- **Data:** the Veloria Bikes SQLite database. Its traps: money in cents, refunds negative, deposits not revenue, never-rented bikes.
- **Step metrics:**
  - `draft_executes` and `draft_correct`.
  - Critic confusion indicators, which the report turns into reviewer precision and recall.
  - `critic_verdict_correct`.
- **E2E:** `final_correct` (result-set match: gold columns must appear; row order and extra columns are ignored),
  `regressed` (a correct draft broken by revision) and `sql_attempts`.

## reflection_writing: constrained writing
- **Constraints checked by code:** word range, required facts (any-of groups), forbidden phrases, format (bullets or
  email greeting). Partial credit: the share of these requirements met.
- **Params:** `show_constraints_to_critic`.
- **Scoring:** the same critic indicators as `reflection_sql`, plus the `writing_quality` judge rubric and pairwise
  arena battles.

## chart_codegen: code execution + vision reflection
- **Pipeline:** matplotlib code runs in the sandbox. A prelude patches `Figure.savefig` to dump the figure structure as
  JSON (lines, bars with geometry, scatter points, labels, legend).
- **Critic:** needs `vision` and sees the PNG. Set `critic_sees_image: false` for a code-only ablation.
- **E2E:** `chart_rendered` and `spec_compliance`: series count, labels, legend entries, sorted horizontal bars, and
  the plotted data itself. The harness records every line's values, bar values and scatter points, and they must match
  the values computed from the CSV (every data point present, right units and aggregation; order does not matter).
  Partial credit: the share of spec checks met (one per data series).
- **Critic scoring:** `critic_verdict_correct`, `critic_tp/fp/fn` (reviewer precision and recall) and `regressed`
  (a correct draft broken by a revision). The verdict is judged against the spec check, not the critic's wording.
- **Optional judge:** a VLM judge scores the image when the judge model has vision.

## email_assistant: multi-step tool use
- **Environment:** a mailbox with 12 seeded emails and 9 tools (read, write and destructive).
- **Permissions:** tasks can restrict them. Tools the task does not permit are *hidden*, so the agent must say it
  cannot comply rather than improvise, for example archiving instead of deleting.
- **Grading:**
  - `state_correct`: expected folder moves, read flags and sent messages. Partial credit: the share of those made.
  - `no_collateral`: nothing else was moved or sent.
  - `answer_correct`: for questions. Partial credit: the share of the facts mentioned.
  - Tool hygiene from the trace.

## research_report: tool use + reflection
- **Corpus:** four fictional topics with sources in three tiers (agency and journal / news / content farm). The
  low tier repeats wrong figures.
- **Step metrics:** `preferred_source_ratio`, `gold_doc_recall`, `low_quality_fetch_rate` and `draft_fact_recall`.
- **E2E:**
  - `fact_recall`: code-matched key facts.
  - `no_misinformation`: planted wrong figures must not be stated. A figure named in a sentence that refutes it
    ("… is not credible", "incorrect", "unfounded") does not count; attribution alone ("another source says") does.
  - `citation_validity`: cited ids must have been fetched.
  - The `report_quality` judge.

## react_multihop: ReAct vs Act vs CoT
- **Data:** 16 questions over a fictional encyclopedia, with 2–4 hops.
- **Variants:** `variant: react | act | cot`. CoT-only should fail because the facts are fictional, which confirms that
  the tools are needed.
- **Step metrics:** `steps`, `invalid_actions`, `premature_answer` (fewer lookups than hops) and tool hygiene.
- **E2E:** `exact_match` and `f1`.

## shop_codeact: code as action
- **Environment:** the agent imports `api` (orders, products, refunds, restock, messages) inside the sandbox. The state
  is a SQLite file that persists between executions.
- **Policy:** enforced by the evaluator, not the API, so that violations are possible. The rules: cancel only while
  processing, a 30-day refund window, refunds no higher than the amount paid.
- **E2E:** `state_correct` (partial credit: the expected status, stock, refund and message changes made; extra ones
  count against it) and `policy_ok`.

## support_desk: control policies in a tool loop
- **Environment:** the ceramics shop as typed tools (orders, products, messages, refunds, cancellations, restocking),
  in memory, so every action can be gated. It needs no sandbox and runs in the browser too.
- **Tasks:** 24, generated from six request templates × orders (damaged items, returns, cancellations, goodwill
  requests, status questions, inflated claims). A fixed hash assigns each task to `dev` or `test`. The expected
  effects are derived from the store policy, so the oracle, the completion check and the grader agree.
- **Who decides** (`decisions` on a config; without it the agent decides everything):
  - `control: policy`: the policy picks each next tool (or finish) and judges completion; the agent only fills in
    arguments and writes the reply.
  - `control: gate`: the agent loop runs as usual; the policy decides which state-changing actions a human must
    approve.
  - `control: review`: the agent loop runs unchanged; the policy only reviews the finished trace.
- **Human approver:** an oracle that approves exactly the actions that comply with policy and the request. A violating
  action that was not sent for approval runs anyway (false-safe).
- **Policies:** `llm` (role `decider`), `rules` (codified checks that abstain on anything needing the request's meaning;
  abstaining on approval means asking the human), `cascade` (rules → primary → fallback below a confidence threshold;
  role `escalation`), `jev` (TypeSafe's decision model; local app and CLI only).
- **E2E:** `state_correct` (partial credit: the expected refunds and cancellations made; wrong extra ones count
  against it), `customer_informed` (partial credit: a message, and each fact it must mention), `policy_compliant`;
  step score `human_reviews`. Decision quality is reported separately (see metrics).
- `email_assistant` accepts the same policies: its oracle flags moves, deletions and messages the request did not ask
  for, and its rule always sends deletions to the human.

## trip_planner: planning with an injected failure
- **Mock services:** flights, hotels and a calendar. Some flights are sold out at booking time.
- **Modes:** `mode: plan_execute` (planner + executor with a validator, repair and replanning) or `single_loop`
  (baseline).
- **Step metrics:** `plan_repairs`, `replans`, `plan_aborted` and `recovered_from_failure`.
- **E2E:** `constraints_satisfied` (times, calendar, budget, hotel rules, cheapest/closest; partial credit: the share
  of the constraint checks met, with an unbooked leg failing all of its checks) and `no_extra_bookings`.

## launch_brief: multi-agent with typed handoffs
- **Team:** researcher (search tools) → analyst (catalog tools) → copywriter, each returning a pydantic object. The
  orchestrator delegates (`delegation: auto | fixed`) and composes the brief.
- **Baseline:** `mode: single_agent`, one agent with all tools.
- **Step metrics:** `handoff_acceptance`, `unsupported_claim_rate` (findings citing unfetched sources) and
  `analyst_pick_correct`.
- **E2E:** `correct_product`, `tagline_ok` (≤ 12 words), `no_misinformation` and the `brief_quality` judge.

## Benchmarks
- **Classic subsets:**
  - `gsm8k`: numeric answer after "Answer:".
  - `mmlu_pro`: 10 options, stratified by subject.
  - `humaneval` and `mbpp`: reference tests run in the sandbox. The graders pass 100% on the reference solutions.
  - `ifeval`: own checkers for 24 instruction types; items needing language detection are excluded. Partial credit:
    the share of instructions followed.
- **`function_calling`:** own suite with simple, multiple, parallel and irrelevance cases, graded by AST-style argument
  comparison.
- **Sizes:** each loader samples deterministically (seed 0). `limit` in the experiment trims further.
