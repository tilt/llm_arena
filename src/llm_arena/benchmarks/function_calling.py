"""Own synthetic function-calling suite: single-turn tool selection and argument filling.

Covers simple, multiple-choice (pick the right tool among many), parallel (several calls in one
turn) and irrelevance (no tool should be called) cases. Graded by comparing call names and
normalised argument trees — a BFCL-style AST check, written from scratch.
"""

from __future__ import annotations

from typing import Any, ClassVar

from llm_arena.benchmarks.base import Benchmark, correct_score
from llm_arena.eval.base import EvalContext, Score, Task, TrialOutput
from llm_arena.llm.client import system, user
from llm_arena.llm.types import LLMResponse
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, register
from llm_arena.scenarios.brief import Expectation, bullet, text


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    parameters = {"type": "object", "properties": properties, "required": required}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


TOOLS = [
    _fn(
        "get_weather",
        "Current weather for a city.",
        {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
        ["city"],
    ),
    _fn(
        "convert_currency",
        "Convert an amount between ISO currencies.",
        {"amount": {"type": "number"}, "from_currency": {"type": "string"}, "to_currency": {"type": "string"}},
        ["amount", "from_currency", "to_currency"],
    ),
    _fn(
        "create_event",
        "Create a calendar event.",
        {
            "title": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "start_time": {"type": "string", "description": "HH:MM, 24h"},
            "duration_minutes": {"type": "integer"},
            "attendees": {"type": "array", "items": {"type": "string"}},
        },
        ["title", "date", "start_time"],
    ),
    _fn(
        "set_timer",
        "Start a countdown timer.",
        {"minutes": {"type": "integer"}, "label": {"type": "string"}},
        ["minutes"],
    ),
    _fn(
        "calculate_tip",
        "Tip amount for a bill.",
        {"bill": {"type": "number"}, "percent": {"type": "number"}},
        ["bill", "percent"],
    ),
    _fn(
        "translate",
        "Translate text.",
        {"text": {"type": "string"}, "target_language": {"type": "string"}},
        ["text", "target_language"],
    ),
    _fn("lookup_order", "Look up a shop order by id.", {"order_id": {"type": "integer"}}, ["order_id"]),
    _fn(
        "send_sms",
        "Send a text message.",
        {"phone": {"type": "string"}, "message": {"type": "string"}},
        ["phone", "message"],
    ),
]

# (id, category, user message, expected calls [(name, required args)])
CASES: list[tuple[str, str, str, list[tuple[str, dict[str, Any]]]]] = [
    ("weather_simple", "simple", "What's the weather in Ostreva right now?", [("get_weather", {"city": "Ostreva"})]),
    (
        "weather_unit",
        "simple",
        "Weather in Pellmoor in fahrenheit please.",
        [("get_weather", {"city": "Pellmoor", "unit": "fahrenheit"})],
    ),
    (
        "currency",
        "simple",
        "How much is 250 euros in Japanese yen?",
        [("convert_currency", {"amount": 250, "from_currency": "EUR", "to_currency": "JPY"})],
    ),
    ("tip", "simple", "What's a 15% tip on a 84.50 bill?", [("calculate_tip", {"bill": 84.5, "percent": 15})]),
    (
        "timer_label",
        "simple",
        "Set a 12 minute timer called pasta.",
        [("set_timer", {"minutes": 12, "label": "pasta"})],
    ),
    ("order", "multiple", "Can you check the status of order 55812?", [("lookup_order", {"order_id": 55812})]),
    (
        "translate",
        "multiple",
        "Translate 'where is the station' into German.",
        [("translate", {"text": "where is the station", "target_language": "German"})],
    ),
    (
        "event",
        "multiple",
        "Put 'Budget review' in my calendar on 2026-07-03 at 14:30 for 45 minutes with priya@quillon.test.",
        [
            (
                "create_event",
                {
                    "title": "Budget review",
                    "date": "2026-07-03",
                    "start_time": "14:30",
                    "duration_minutes": 45,
                    "attendees": ["priya@quillon.test"],
                },
            )
        ],
    ),
    (
        "sms",
        "multiple",
        "Text +44 7700 900123 saying 'Running 10 minutes late'.",
        [("send_sms", {"phone": "+44 7700 900123", "message": "Running 10 minutes late"})],
    ),
    (
        "parallel_weather",
        "parallel",
        "Compare the weather in Varrel and Quistra.",
        [("get_weather", {"city": "Varrel"}), ("get_weather", {"city": "Quistra"})],
    ),
    (
        "parallel_mixed",
        "parallel",
        "Set a 5 minute timer and convert 40 USD to EUR.",
        [
            ("set_timer", {"minutes": 5}),
            ("convert_currency", {"amount": 40, "from_currency": "USD", "to_currency": "EUR"}),
        ],
    ),
    (
        "parallel_translate",
        "parallel",
        "Translate 'thank you' into French and into Spanish.",
        [
            ("translate", {"text": "thank you", "target_language": "French"}),
            ("translate", {"text": "thank you", "target_language": "Spanish"}),
        ],
    ),
    ("irrelevant_fact", "irrelevance", "Who wrote the novel 'Middlemarch'?", []),
    ("irrelevant_math", "irrelevance", "What is 17 times 23?", []),
    ("irrelevant_chat", "irrelevance", "Thanks, that's all for today!", []),
    ("irrelevant_near_miss", "irrelevance", "What's the weather usually like in deserts at night, in general?", []),
]


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return round(float(value), 4)
    if isinstance(value, str):
        return " ".join(value.lower().replace("’", "'").strip().strip("'\"").split())
    if isinstance(value, list):
        return sorted((_norm(v) for v in value), key=str)
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    return value


def call_matches(expected: tuple[str, dict[str, Any]], name: str, args: dict[str, Any]) -> bool:
    """Expected arguments must match exactly (after normalisation); extra optional args are allowed."""
    expected_name, expected_args = expected
    return name == expected_name and all(_norm(args.get(k)) == _norm(v) for k, v in expected_args.items())


@register
class FunctionCallingBench(Benchmark):
    name = "function_calling"
    title = "Function calling"
    tokens_per_trial = 700
    description = "Own synthetic suite: simple/multiple/parallel/irrelevance tool calls, AST-style argument check."
    sample_size = len(CASES)

    roles = [RoleRequirement("model", "the model under test", kind="agent")]
    grading: ClassVar[str] = "exactly the expected tool calls with matching arguments (none for irrelevant requests)"

    def expected(self, task: Task) -> list[Expectation]:
        calls = [f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())})" for name, args in task.data["expected"]]
        return [
            bullet("Expected calls", calls or ["no call: the request needs no tool"]),
            text("Category", task.data["category"]),
        ]

    def load_tasks(self) -> list[Task]:
        return [
            Task(
                id=case_id,
                prompt=message,
                data={"expected": [[n, a] for n, a in calls], "category": category},
                tags=[category],
            )
            for case_id, category, message, calls in CASES
        ]

    def fixtures(self) -> dict[str, Any]:
        return {"tools.json": TOOLS}

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        with ctx.trace.in_step("answer"):
            response = await self._answer(task, models)
        return self._output(response)

    async def _answer(self, task: Task, models: RoleModels) -> LLMResponse:
        return await models["model"].complete(
            [
                system("Use a tool only when it is needed to answer. Call all needed tools in one reply."),
                user(task.prompt),
            ],
            tools=TOOLS,
        )

    def _output(self, response: LLMResponse) -> TrialOutput:
        calls = [{"name": call.name, "args": call.args} for call in response.tool_calls]
        return TrialOutput(final=response.content, extras={"calls": calls})

    async def grade(self, ctx: EvalContext) -> list[Score]:
        expected = [(name, args) for name, args in ctx.task.data["expected"]]
        calls = list(ctx.output.extras["calls"])
        unmatched = list(calls)
        for wanted in expected:
            match = next((c for c in unmatched if call_matches(wanted, c["name"], c["args"])), None)
            if match is not None:
                unmatched.remove(match)
        all_found = len(calls) - len(unmatched) == len(expected)
        correct = all_found and not unmatched
        names_ok = sorted(c["name"] for c in calls) == sorted(name for name, _ in expected)
        return [
            correct_score(correct, f"calls={calls}"),
            Score(name="tool_names_correct", value=float(names_ok), level="step", passed=names_ok),
            Score(name=f"correct.{ctx.task.data['category']}", value=float(correct), level="e2e"),
        ]
