# Provenance

The arena was inspired by Andrew Ng's *Agentic AI* course (deeplearning.ai), which lives in `../course_agentic_ai`.
That material is protected. **Nothing from it is copied into this repository**: no code, prompts, notebook text,
datasets, fixture emails, schemas or helper modules.

What we took is general, widely published ideas. Everything was reimplemented from scratch, with new domains and
fictional entities. The methodology follows our own wiki (`data-science-wiki/content/11-generative-ai/`).
`tests/test_provenance.py` checks for accidental verbatim overlap with the course files (20-token shingles).

| Arena component | General idea | Our sources |
|---|---|---|
| `reflection_sql` | Reflection works better with external feedback (execution results) than with self-review alone | wiki `reflection-and-reviewer-patterns.md` (Reflexion, reviewer as classifier) |
| `reflection_writing`, `chart_codegen` | Draft → critique → revise; a multimodal critic for rendered output | wiki reflection page; figure introspection is our own design |
| `email_assistant`, mock mailbox | Tool use against a mock service; permission scoping | wiki `tool-use-and-function-calling.md`, `agent-evaluation.md`; state-based grading after τ-bench |
| `research_report` | Evaluate the retrieval component separately (source quality) from end-to-end quality | wiki `evaluation-harnesses.md`, `pipeline-improvement-methodology.md` |
| `react_multihop` | ReAct vs Act-only vs CoT ablation | wiki `agent-loops.md` (ReAct paper setup) |
| `shop_codeact` | Code as action (CodeAct) | wiki `agent-loops.md` § Code as an action |
| `trip_planner` | Plan-and-execute, validator, replanning | wiki `planning.md` |
| `launch_brief` | Orchestrator–workers, typed handoffs, single-agent baseline | wiki `multi-agent-systems.md` (MAST, protocol over personas) |
| LLM client utilities | Native vs JSON tool mode; reasoning-model quirks | the user's own `rag_agent/agent/llm.py` and `docquet` config (same author) |

When you add a scenario, add a row here.
