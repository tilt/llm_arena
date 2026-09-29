# Metrics

| Metric | Definition | Where |
|---|---|---|
| Trial passed | status ok **and** every pass-criterion score of the scenario that produced a verdict passed (at least one must exist) | `runner/run.py` |
| Pass rate [95% CI] | mean of trial passes; percentile bootstrap (2000 resamples) | `eval/metrics.bootstrap_ci` |
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
  (0.67) ranks below 3 of 3 (0.80). The table still shows the plain pass rate.
- **vs #1:** difference to the leader on the tasks both ran, with a paired permutation test.
- **Legacy runs** (from before fingerprints) form their own `legacy` board and never mix with versioned results.
- **Bump `Scenario.version`** whenever prompts, tools, evaluators or pass criteria change; otherwise old and new
  results would pool.

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
