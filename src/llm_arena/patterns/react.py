"""ReAct as a plain-text protocol (Thought / Action / Action Input / Observation).

Deliberately independent of native tool calling, so any chat model can play, and the three
classic ablations run on the same tools and tasks:
  react — reason, then act;   act — act without written thoughts;   cot — reason, no tools.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient
from llm_arena.llm.jsonutil import extract_json
from llm_arena.llm.types import Message, ToolCall
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.tool_docs import describe_tools

Variant = Literal["react", "act", "cot"]

_FINAL = re.compile(r"Final Answer\s*:\s*(.*)", re.DOTALL | re.IGNORECASE)
_ACTION = re.compile(r"Action\s*:\s*([A-Za-z_][\w\-]*)\s*(?:\[(.*?)\])?", re.IGNORECASE)
_ACTION_INPUT = re.compile(r"Action Input\s*:\s*(.*)", re.DOTALL | re.IGNORECASE)

_PROTOCOLS: dict[Variant, str] = {
    "react": (
        "Solve the task step by step. In every reply write exactly one of:\n"
        "Thought: <your reasoning about what to do next>\nAction: <tool name>\nAction Input: <JSON object of arguments>\n"
        "or, once you are certain:\nThought: <why you are done>\nFinal Answer: <the answer only>\n"
        "After each action you will receive an Observation. Never write an Observation yourself."
    ),
    "act": (
        "Solve the task using the tools. In every reply write exactly one of:\n"
        "Action: <tool name>\nAction Input: <JSON object of arguments>\n"
        "or\nFinal Answer: <the answer only>\n"
        "Do not explain your reasoning. After each action you will receive an Observation."
    ),
    "cot": (
        "Answer from your own knowledge; no tools are available. Think step by step, then end with\n"
        "Final Answer: <the answer only>"
    ),
}


@dataclass
class ReactResult:
    final: str
    stop_reason: Literal["final", "max_steps"]
    steps: int
    invalid_actions: int
    messages: list[Message]


def parse_react_reply(text: str) -> tuple[str | None, ToolCall | None]:
    """Return (final_answer, action). Text after a self-written Observation is ignored."""
    text = re.split(r"\n\s*Observation\s*:", text, maxsplit=1)[0]
    action_match = _ACTION.search(text)
    final_match = _FINAL.search(text)
    # If both appear, whichever comes first wins: models sometimes act and then hallucinate a final answer.
    if final_match and (not action_match or final_match.start() < action_match.start()):
        return final_match.group(1).strip(), None
    if not action_match:
        return None, None
    raw_args = action_match.group(2)
    if raw_args is None and (input_match := _ACTION_INPUT.search(text)):
        raw_args = input_match.group(1).strip()
    args: dict[str, object] = {}
    if raw_args:
        try:
            parsed = extract_json(raw_args)
            args = parsed if isinstance(parsed, dict) else {"query": parsed}
        except ValueError:
            args = {"query": raw_args.strip().strip('"')}
    return None, ToolCall(name=action_match.group(1), args=args, raw_args=raw_args)


async def run_react(
    llm: LLMClient,
    task: str,
    executor: ToolExecutor,
    trace: Trace,
    *,
    variant: Variant = "react",
    max_steps: int = 8,
    extra_instructions: str = "",
) -> ReactResult:
    tools_doc = "" if variant == "cot" else f"\n\nTools:\n{describe_tools(executor.registry)}"
    history: list[Message] = [
        {"role": "system", "content": f"{_PROTOCOLS[variant]}{tools_doc}{extra_instructions}"},
        {"role": "user", "content": f"Task: {task}"},
    ]
    invalid = 0
    for step in range(1, max_steps + 1):
        response = await llm.complete(history)
        history.append({"role": "assistant", "content": response.content})
        final, action = parse_react_reply(response.content)
        if final is not None:
            return ReactResult(final, "final", step, invalid, history)
        if action is None or variant == "cot":
            invalid += 1
            with trace.span("step", "invalid_action", attrs={"step": step}) as span:
                span.error = "reply had neither a parseable Action nor a Final Answer"
            history.append({"role": "user", "content": "Observation: invalid format. Follow the protocol exactly."})
            continue
        outcome = await executor.execute(action)
        history.append({"role": "user", "content": f"Observation: {outcome.content}"})
    return ReactResult("", "max_steps", max_steps, invalid, history)


def format_args(args: dict[str, object]) -> str:
    return json.dumps(args, ensure_ascii=False)
