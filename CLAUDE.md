Read AGENTS.md first: it holds the layout, the change loop (`make format && make test`) and the copyright rules for
the course material.

Quick orientation:
- `uv run arena scenarios` lists every scenario with its roles.
- `uv run arena run configs/experiments/smoke.yaml --dry-run` shows how an experiment expands into trials.
- Tests never need a model server: use `llm_arena.llm.testing.ScriptedLLM` and `tool_call(...)`.
