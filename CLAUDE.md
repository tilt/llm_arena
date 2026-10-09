Read AGENTS.md first: it holds the layout, the change loop (`make format && make test`) and the copyright rules for
the course material.

Quick orientation:
- `uv run arena scenarios` lists every scenario with its roles.
- `uv run arena run configs/experiments/smoke.yaml --dry-run` shows how an experiment expands into trials.
- Tests never need a model server: use `llm_arena.llm.testing.ScriptedLLM` and `tool_call(...)`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. Route only to skills in the session's available-skills list; answer directly for quick questions or small scoped edits.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
