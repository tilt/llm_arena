"""Scenario-independent step metrics read from the trace (tool hygiene, loop behaviour)."""

from __future__ import annotations

import json

from llm_arena.eval.base import EvalContext, Score, ratio_score


class ToolHygieneEvaluator:
    """Argument validity, unknown/forbidden tools, redundant calls, and tool errors.

    These are the 'tool arguments' and 'permissions' layers of the agent-evaluation trace model.
    """

    name = "tool_hygiene"

    async def evaluate(self, ctx: EvalContext) -> list[Score]:
        calls = ctx.trace.select("tool_call")
        if not calls:
            return [Score(name="tool_calls", value=0, level="step", rationale="no tool calls")]
        kinds = [span.attrs.get("error_kind") for span in calls]
        signatures = [f"{span.name}:{json.dumps(span.input, sort_keys=True, default=str)}" for span in calls]
        redundant = len(signatures) - len(set(signatures))
        return [
            Score(name="tool_calls", value=len(calls), level="step"),
            ratio_score("tool_arg_validity", sum(k != "invalid_args" for k in kinds), len(calls), "step"),
            ratio_score("tool_name_validity", sum(k != "unknown_tool" for k in kinds), len(calls), "step"),
            ratio_score("tool_success_rate", sum(k is None for k in kinds), len(calls), "step"),
            ratio_score("redundant_call_rate", redundant, len(calls), "step", empty=0.0),
            Score(
                name="forbidden_attempts",
                value=sum(k in ("forbidden", "unknown_tool") for k in kinds),
                level="step",
                passed=not any(k in ("forbidden", "unknown_tool") for k in kinds),
            ),
        ]


class StopReasonEvaluator:
    """Did the loop end with an answer, or run out of turns? (read from output.extras['stop_reason'])"""

    name = "stop_reason"

    async def evaluate(self, ctx: EvalContext) -> list[Score]:
        reason = ctx.output.extras.get("stop_reason")
        if reason is None:
            return []
        return [
            Score(
                name="finished_cleanly",
                value=1.0 if reason == "final" else 0.0,
                level="step",
                passed=reason == "final",
                rationale=str(reason),
            )
        ]
