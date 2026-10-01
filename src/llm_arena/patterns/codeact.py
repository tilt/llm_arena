"""Code as action: the model writes Python against a documented API; we execute it and show the output.

The environment supplies the files for each run (an API module plus its state) and absorbs the
state back after every execution, so actions persist across steps like calls to a real service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient
from llm_arena.llm.types import Message
from llm_arena.sandbox.base import ExecResult, Sandbox

_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_FINAL = re.compile(r"FINAL ANSWER\s*:\s*(.*)", re.DOTALL | re.IGNORECASE)


class CodeEnvironment(Protocol):
    api_doc: str

    def files(self) -> dict[str, bytes | str]: ...

    def absorb(self, result: ExecResult) -> None: ...


@dataclass
class CodeActResult:
    final: str
    stop_reason: Literal["final", "max_steps"]
    steps: int
    executions: int
    failed_executions: int
    messages: list[Message]


def extract_code(text: str) -> str | None:
    blocks = _CODE_BLOCK.findall(text)
    return "\n\n".join(block.strip() for block in blocks) if blocks else None


async def run_codeact(
    llm: LLMClient,
    task: str,
    environment: CodeEnvironment,
    sandbox: Sandbox,
    trace: Trace,
    *,
    max_steps: int = 6,
    timeout_s: float = 20.0,
    system_prompt: str = "",
) -> CodeActResult:
    history: list[Message] = [
        {
            "role": "system",
            "content": (
                f"{system_prompt}\n\nYou act by writing Python. Put code in one ```python block per reply; "
                "it runs in a fresh process and you will see stdout/stderr. Use print() to inspect data. "
                "State changes made through the API persist between runs. When the task is complete, reply with\n"
                "FINAL ANSWER: <short summary for the customer/user>\n\n"
                f"Available API (import from `api`):\n{environment.api_doc}"
            ).strip(),
        },
        {"role": "user", "content": task},
    ]
    executions = failed = 0
    for step in range(1, max_steps + 1):
        with trace.in_step("code"):
            response = await llm.complete(history)
        history.append({"role": "assistant", "content": response.content})
        code = extract_code(response.content)
        if code is None:
            final_match = _FINAL.search(response.content)
            final = final_match.group(1).strip() if final_match else response.content.strip()
            return CodeActResult(final, "final", step, executions, failed, history)
        with trace.in_step("exec"), trace.span("code_exec", "python", input=code, attrs={"step": step}) as span:
            result = await sandbox.run(code, files=environment.files(), collect=("state/*",), timeout_s=timeout_s)
            environment.absorb(result)
            span.output = result.observation()
            span.attrs.update(
                {
                    "ok": result.ok,
                    "timed_out": result.timed_out,
                    "output_truncated": result.output_truncated,
                    "omitted": result.omitted,
                    "duration_s": result.duration_s,
                }
            )
        executions += 1
        failed += 0 if result.ok else 1
        history.append({"role": "user", "content": f"Execution result:\n{result.observation()}"})
    return CodeActResult("", "max_steps", max_steps, executions, failed, history)
