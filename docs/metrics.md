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
| Cost | tokens × price table (override per model); local models 0 $, latency still reported | `llm/pricing.py` |

## Interpreting results

- **Small samples.** With few tasks, the confidence intervals are wide. The report warns when a paired comparison
  rests on fewer than 20 tasks.
- **Agentic scenarios need repeats.** Use `repeats ≥ 3`. pass^k often separates configurations that tie on pass rate.
- **Compare against a budget-matched baseline** before crediting a pattern. The arena has these switches:
  `reflection_rounds: 0`, `mode: single_loop`, `mode: single_agent`, `variant: cot`.
- **A score belongs to a model–harness pair.** The same model can score differently in native and JSON tool mode, or
  through the OpenAI SDK and aisuite.
