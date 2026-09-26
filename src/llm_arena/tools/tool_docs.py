"""Human-readable tool documentation for text protocols (ReAct, CodeAct, planners)."""

from __future__ import annotations

from llm_arena.llm.tool_mode import render_tool_docs
from llm_arena.tools.registry import ToolRegistry


def describe_tools(registry: ToolRegistry) -> str:
    return render_tool_docs(registry.schemas())
