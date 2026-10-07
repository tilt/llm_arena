# Benchmarking and rating principles

Why the arena grades and ranks the way it does. Formulas are in [metrics.md](metrics.md), per-scenario details in
[scenarios.md](scenarios.md), and the contributor rules that enforce these principles in [AGENTS.md](../AGENTS.md).

A score is only worth something if a reader can trust three things:
- **It measures what it claims.** The grader checks the property the task is about.
- **It can be reproduced.** The same setup on the same tasks gives the same evidence.
- **It is compared fairly.** It is set only against results that ran under the same conditions.

Every principle below serves one of these three.

## 1. What a score measures

**Grade outcomes, not claims.** An agent's final message can say anything. Scenarios grade what it *did*: the final
mailbox, shop database, bookings or SQL result set. This is state-based grading, as in τ-bench. The final text is only
graded when the answer is the outcome (questions, reports, briefs).

**Grade with code where the truth is objective.** State diffs, result sets, constraints, numbers and citations are
checked by code: it is cheap, deterministic and explainable. An LLM judge scores only what code cannot check (tone,
coherence, image quality). It is never the only pass criterion, and its agreement with hand labels is measured
(Cohen's κ; below 0.6 is flagged).

**Passing means safe *and* good.** A trial passes only when every pass criterion holds: the expected work is done
**and** nothing else was damaged, no policy was broken, no misinformation was stated. A task finished with collateral
damage is a failure, not a near miss.

**Grade the meaning, not the surface.** A check must not punish correct behaviour that happens to share words with the
mistake it looks for. Naming a wrong figure in order to refute it is not misinformation. A substring match that cannot
tell the two apart is a grader bug.

**Grade what the agent was told.** If a rule decides the verdict, the agent must have been able to know it, from the
task, the system prompt or the policy it was given. Otherwise the score measures guessing the grader.

**Separate steps from outcomes.** Step metrics are diagnostics, not pass criteria:
- critic precision and recall;
- plan repairs;
- handoff acceptance;
- tool hygiene;
- decision quality against an oracle.

They explain *why* a pipeline succeeds or fails, and they make a model's contribution to one step measurable. They do
not change whether the trial passed.

## 2. Pass rate and partial credit

**The pass rate is the headline.** It answers the question a user has: does this setup get the job done? It ranks the
leaderboard and drives every comparison and significance test.

**Partial credit explains the pass rate; it never replaces it.** Without it, a trial that did three of four things
looks like one that did nothing. A board full of 0% says nothing about which setup came closest or which gate blocks
everyone. Partial credit is the share of the graded work done. It is shown next to the pass rate, broken down per pass
criterion when a setup is expanded, and used only to break ranking ties.

Partial credit follows rules that keep it honest:
- **100% only when the trial passed.** A failed trial always stays below a passed one.
- **The denominator comes from the task.** It is fixed by the task's expectations, never by what the agent happened to
  do, so doing less can never raise the score.
- **No credit for doing nothing.** For state checks, only the expected changes the initial state lacked count as work.
  An expectation that was already met earns nothing for leaving it alone.
- **Damage costs credit.** Breaking something that was correct before adds a failed check.
- **Safety is all-or-nothing within its share.** Each pass criterion weighs the same. A safety criterion is either kept
  or broken: a policy violation can't be half-avoided.
- **No partial credit where parts are meaningless.** Some answers stay binary:
  - a single-entity answer;
  - a SQL result set, where row overlap would reward `SELECT *`;
  - a multiple-choice pick.

**When a criterion is 0% for every setup, suspect the task first.** Before reading it as a model weakness, read the
failure rationales. A criterion that nobody passes is usually one of these:
- a grader bug;
- a rule the agent was never told;
- a harness problem (for example, the agent replies in text because the reply tool is unclear).

## 3. Reproducibility and attribution

**Same setup, same evidence.** Hidden state must not move scores:
- Mock environments are seeded.
- Trials do not share mutable fixtures.
- Nothing depends on the wall clock or the network unless a run is explicitly live.

**Every result can be traced back.**
- Every model call is attributed to a role.
- Every trial persists its trace, scores and rationales.
- Every leaderboard cell links to the step inspector.

A number nobody can open is not evidence.

**Fictional domains, fresh data.** Tasks use invented companies, places and figures, so a model cannot pass from
memory. A chain-of-thought-only baseline should fail the tool-use scenarios, and that failure is a useful check that
the tools are needed. Public benchmarks are downloaded at a pinned revision and never vendored.

## 4. Fair comparison

**Compare like with like.** A leaderboard entry is a *setup*: each role's model and call settings, the scenario
parameters and the control policy, hashed into a fingerprint. Config names are labels only. Results pool only within
the same scenario version and fingerprint.

**Version the yardstick.** Bump `Scenario.version` whenever prompts, tools, evaluators or pass criteria change. Old
and new results then form separate boards instead of silently mixing. An edited task counts as a new task because of
its content hash. Runs from before fingerprints sit on a separate legacy board.

**Re-grade instead of rerunning when only the yardstick moved.** If prompts, tools and tasks are unchanged, what the
agent did is still valid evidence: the earlier version goes into `regrades_from`, and `arena regrade` recomputes the
verdicts of its stored trials with the current evaluators. Any change to what the agent saw or could do needs a
rerun.

**A score belongs to a model–harness pair.** Tool mode (native or JSON), SDK backend and reasoning settings change
results. They are part of the setup, not noise.

**Count failures honestly.**
- Errors and timeouts count as fails: a setup that crashes does not get the job done.
- Trials stopped by a spend limit are excluded, because they never ran.
- A comparison where every trial of a swap errored is reported as *not measurable*, not as a model effect.

**Compare against a budget-matched baseline.** Before crediting a pattern (reflection, planning, multiple agents,
control policies), run its cheap ablation on the same tasks. The ablations are listed in [metrics.md](metrics.md).

**Tune on dev, report on test.** A threshold fitted to the tasks it is scored on is overfitted by construction.

## 5. Uncertainty

**Every task weighs the same.** Pass rate and partial credit are means over tasks of the per-task share. A task that
ran ten times counts once.

**Show the interval, not just the point.**
- Confidence intervals bootstrap over tasks.
- Leaderboard differences use paired permutation tests on the tasks both setups ran.
- Comparisons that rest on fewer than 20 tasks are flagged.

**Discount thin evidence.** The ranking shrinks the pass rate towards 50% by the number of tasks, so one lucky task does
not outrank a setup that passed most of many. Ties (common at 0% and 100%) go to partial credit, then cost.

**Agents are stochastic: repeat them.** Use at least 3 repeats for agentic scenarios. pass^k (all k repeats pass)
measures reliability and often separates setups that tie on pass rate.

## Checklist for a new or changed scenario

- [ ] Outcomes are graded from state or answers by code. Any judge is calibrated and is not the sole pass criterion.
- [ ] Pass criteria cover quality **and** safety.
- [ ] Every rule that decides a verdict is visible to the agent.
- [ ] Each pass criterion reports its partial credit as `value`:
  - the denominator comes from the task;
  - doing nothing earns 0;
  - breakage counts against the credit;
  - safety criteria stay binary;
  - criteria stay binary where parts are meaningless.
- [ ] Tests:
  - a scripted good agent passes;
  - a scripted bad agent fails the intended check;
  - a half-done agent earns the expected partial credit;
  - correct behaviour that resembles the mistake (refuting, declining, asking) is not penalised.
- [ ] Data is fictional and its origin is recorded in [PROVENANCE.md](PROVENANCE.md).
- [ ] `Scenario.version` is bumped if anything that affects scores changed.
- [ ] If only grading changed, the previous version is listed in `regrades_from` and old runs are re-graded with
  `arena regrade`.
