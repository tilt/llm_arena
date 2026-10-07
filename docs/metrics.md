# Metrics

How each number is computed. Why it is computed that way is in [principles.md](principles.md).

| Metric | Definition | Where |
|---|---|---|
| Trial passed | status ok **and** every pass-criterion score of the scenario that produced a verdict passed (at least one must exist) | `runner/run.py` |
| Pass rate [95% CI] | mean of trial passes; percentile bootstrap (2000 resamples) | `eval/metrics.bootstrap_ci` |
| Partial credit | per trial: mean over the graded pass criteria of each one's credit (1 if it passed, else its value if that is a share in [0, 1), else 0); errors and timeouts 0. It is 1 exactly when the trial passed. State checks count only the expected changes the initial state lacked, over those plus any expectation the agent broke, so doing nothing earns 0 and collateral costs credit. Safety criteria are all-or-nothing | `eval/credit.py` |
| pass@k | per task, unbiased estimate that ≥1 of k repeats passes; averaged over tasks | `pass_at_k` |
| pass^k | per task, probability that all k repeats pass (τ-bench reliability); averaged | `pass_hat_k` |
| Paired test | leader vs each config on shared tasks (per-task pass means), two-sided sign-flip permutation test | `paired_permutation_test` |
| Reviewer precision / recall | from critic indicator means: TP/(TP+FP), TP/(TP+FN), where "positive" = draft was wrong | `report/aggregate._derived` |
| Tool hygiene | argument validity, name validity, success rate, redundant-call rate, forbidden attempts | `eval/trace_checks.py` |
| Judge rubric | per-criterion 1–5 scores, normalised to 0–1, weighted; skipped criteria score the minimum | `eval/judge.py` |
| Judge calibration | raw agreement + Cohen's κ against hand labels; κ < 0.6 flagged | `eval/calibration.py` |
| Arena rating | Bradley–Terry (MM algorithm, ties = ½ win, small prior) on Elo scale around 1000 | `bradley_terry` |
| Decision accuracy | per config × decision point × question: share of labeled, non-abstained answers equal to the ground truth | `decisions/records.py` |
| Brier / log loss | mean squared error of the answer's probabilities vs the one-hot label; −log P(label), clipped at 1e-6 | `decisions/records.py` |
| Missed / false alarms | yes/no questions: P(pred false \| label true) and P(pred true \| label false). For approval and review questions, *missed* is the false-safe rate and *false alarms* are needless human escalations | `decisions/records.py` |
| Calibration | five P(true) bins: mean predicted probability vs observed share of true labels | `decisions/records.py` |
| Decision latency / cost | p50/p95 per decision request; LLM stages cost their tokens, Jev its input tokens ($0.042 / M) | `decisions/records.py` |
| Cost | tokens × price table (override per model); local models 0 $, latency still reported | `llm/pricing.py` |

## Leaderboard across runs

`arena leaderboard [scenario]`, `GET /api/leaderboard` and the **Leaderboard** page pool every run:

- **Grouping:** by scenario, scenario `version` and *setup fingerprint*. The fingerprint hashes each role's model and
  call settings (provider, model, backend, tool mode, temperature, reasoning effort, max tokens), the scenario
  parameters and the control policy. Config names are labels only: a renamed config pools with its earlier runs,
  and a changed setup under an old name does not.
- **Tasks:** identified by id *and* content hash, so an edited task counts as a new task.
- **Pass rate:** mean over tasks of the per-task pass share, so every task weighs the same however often it ran. The
  95% interval bootstraps over tasks. Errors and timeouts count as fails; trials stopped by a spend limit are left out.
- **Ranking:** by (passes + 1) / (tasks + 2), the pass rate shrunk towards 50% by the amount of evidence: 1 of 1 task
  (0.67) ranks below 3 of 3 (0.80). The table still shows the plain pass rate. Ties (common at 0% and 100%) go to
  the setup with more partial credit, then the cheaper one.
- **Partial credit and criteria:** the *Partial* column is the mean over tasks of each task's mean credit. An expanded
  setup shows every pass criterion's pass rate and the share of its checks met, which tells you which gate holds a
  setup back. Errors and timeouts count as failing every criterion of their task (the criteria its graded trials
  had), as they fail the pass rate.
- **Runs stored before partial credit** get it from their stored score values, as graded then: sub-checks added
  since cannot be recovered, so an old binary criterion stays 0 or 1. The scenario's current pass criteria are used;
  where the result contradicts the stored verdict (the old version graded other criteria), credit stays unknown.
- **vs #1:** difference to the leader on the tasks both ran, with a paired permutation test.
- **Legacy runs** (from before fingerprints) form their own `legacy` board and never mix with versioned results.
- **Bump `Scenario.version`** whenever prompts, tools, evaluators or pass criteria change; otherwise old and new
  results would pool.
- **Re-grading:** when only evaluators or pass criteria changed, list the previous version in
  `Scenario.regrades_from`. `arena regrade` then re-grades that version's stored trials with the current evaluators
  (from their final output, environment state, extras, trace and result files) and moves them to the current version.
  - Trials stay on the old board when their task changed, when their trace or result files are missing, or when a
    current evaluator fails on them: a verdict is only replaced by a complete new one.
  - Judge rubric scores need a model, so they are carried over from the original grading. Nothing else is, and
    never a pass criterion, so no verdict or credit comes from the old grading.
  - The database and the traces change together: new traces are staged, the database commits or rolls back, and
    only then are the traces swapped in.
  - Resume keys are updated, so a resumed run does not rerun re-graded trials.
  - The trace records `regraded: {from_version, passed_before}`.
  - Legacy runs (no version or fingerprint) cannot be re-graded.

**Pass criteria report their credit as their value.** A pass criterion's `value` is its credit and `passed` its
verdict, so e2e means of pass criteria in a run report are mean credit; for example, `state_correct` 0.83 means 83% of
the expected changes were made. Scenarios whose ground truth has no meaningful parts keep binary criteria:
`reflection_sql` (result-set overlap is easy to game), `react_multihop` (one answer; `f1` is a diagnostic), and the
classic benchmarks except `ifeval`.

## Replacement effects

For a replacement study, each configuration that swaps one role is compared with the baseline configuration of the
same scenario:
- **Δ pass rate:** on the tasks both ran (per-task pass shares, averaged).
- **p:** a paired permutation test on those tasks.
- **Δ cost and Δ p50 latency:** per trial.
- **Step metrics:** changes in the step-level metrics.

Errored trials count as fails in the pass rate, but they are reported with the effect. A swap where every trial
errored (a missing model, an exhausted quota) is shown as *not measurable*, not as a model effect.

## Interpreting results

- **Small samples.** With few tasks, the confidence intervals are wide. The report warns when a paired comparison
  rests on fewer than 20 tasks.
- **Agentic scenarios need repeats.** Use `repeats ≥ 3`. pass^k often separates configurations that tie on pass rate.
- **Compare against a budget-matched baseline** before crediting a pattern. The arena has these switches:
  `reflection_rounds: 0`, `mode: single_loop`, `mode: single_agent`, `variant: cot`.
- **Tune decision thresholds on `split: dev`, report on `split: test`.** Otherwise the cascade threshold is fitted to
  the tasks it is scored on. LLM probabilities are verbalised estimates: check the calibration bins before trusting a
  threshold.
- **A score belongs to a model–harness pair.** The same model can score differently in native and JSON tool mode, or
  through the OpenAI SDK and aisuite.
