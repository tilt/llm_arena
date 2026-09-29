# How the arena relates to existing evaluation tools

There are excellent open-source evaluation frameworks and agent benchmarks. The arena is not a replacement for them.
It fills a narrower niche: **controlled experiments on agentic workflows with a model chosen per step**, mostly
with local models, on deterministic tasks whose ground truth is known for every step.

## Overlap

| Tool | What it is | Overlap with the arena |
|---|---|---|
| Inspect AI | Framework for tasks, solvers and scorers, with sandboxes, agent support and a log viewer | High: tasks, scorers, sandboxes, traces. Inspect is the more general framework. |
| OpenAI Evals | A registry of evals with model-graded and rule-based checks | Medium: eval definitions and model-graded scoring |
| DeepEval, promptfoo | Test frameworks for LLM applications (assertions, metrics, CI) | Medium: metrics, regression testing of prompts and models |
| τ-bench | Tool-agent-user benchmark with domain policies and state-based grading | High for `support_desk` and `email_assistant`, which grade the final environment state against a policy in the same spirit |
| BFCL | Berkeley Function-Calling Leaderboard | High for the `function_calling` suite (AST-style argument matching) |
| AgentBench, WebArena | Multi-environment and realistic web environments for agents | Low to medium: the arena's environments are small mocks, not realistic sites or OSes |
| SWE-bench | Repository-level software engineering tasks | Low: the arena's code tasks are small (HumanEval/MBPP subsets, CodeAct on a mock shop) |

## What is different here

- **A model per step, not per run.** Every pipeline step is bound to a role, and every role can run a different
  model. For example: a small local drafter with a remote critic, a planner separate from its executor, or a
  dedicated decision model gating actions.
  - *Replacement studies* swap exactly one step's model against a baseline preset. They report the effect with a
    paired test on shared tasks.
  - The leaderboard pools runs by a fingerprint of the complete setup, so combinations stay separate even under
    reused config names.
- **Ground truth for each step.** Scenarios declare their workflow, and spans are linked to its steps. Step-level
  evaluators and control decisions are scored against known labels: critic precision and recall, plan repairs,
  handoff acceptance, approval decisions against an oracle. The *step inspector* shows each step's input, output
  and files.
- **Control policies as an experimental dimension.** The same agent is compared with decisions made by the agent
  itself, by rules, by an LLM, by cascades, or by dedicated decision models (Jev, winnow via Ollaya). The comparison
  covers accuracy, calibration and false-safe rates.
- **Local-first.** Installed Ollama, LM Studio and Ollaya models are discovered with their capabilities and run
  serialized per endpoint, so latencies stay honest. A thinking-off setting per reference makes small models
  practical.
- **One engine, three front ends.** The CLI, a local app, and a browser-only build on GitHub Pages all run the same
  Python engine (Pyodide in the browser). Conformance vectors check the three agree.

## When to use something else

- **Established public numbers:** use the benchmark's own harness, such as BFCL, τ-bench, SWE-bench or WebArena. The
  arena's scenarios are synthetic and small by design, and its benchmark subsets are samples.
- **A general evaluation framework for your own application:** Inspect AI, DeepEval or promptfoo are broader and have
  larger ecosystems.
- **Realistic, open-ended environments** (real websites, operating systems, repositories): use AgentBench, WebArena
  or SWE-bench.

## Interoperability, today and next

- **Today:**
  - Run bundles (JSON) contain trials, scores, traces and artifacts.
  - `arena leaderboard --json` and `arena report --json` export results.
  - JSON Schemas for every exchanged object are in `contracts/schemas`.
- **Next steps:**
  - Export runs as Inspect-style eval logs.
  - Import τ-bench and BFCL task files as arena scenarios, so the arena's per-step and replacement analyses can run
    on public tasks.
