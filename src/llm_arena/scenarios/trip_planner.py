"""Scenario: constrained trip booking — plan-and-execute with replanning vs a single tool loop.

A flight that looks available is sold out at booking time, so a good agent must notice and
recover. Hard constraints (times, budget, calendar, hotel rules) are checked by code against
the confirmed bookings; plan quality is scored from the planning trace.
"""

from __future__ import annotations

from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.trace_checks import ToolHygieneEvaluator
from llm_arena.llm.client import system, user
from llm_arena.mocks.travel import CALENDAR, FLIGHTS, HOTELS, TravelAgency
from llm_arena.patterns.planning import basic_validator, plan_and_execute
from llm_arena.patterns.roles import RoleModels
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register
from llm_arena.scenarios.brief import Brief, TaskView, bullet
from llm_arena.scenarios.workflow import END, START, Workflow, edge, step, when
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.registry import ToolRegistry

TASKS: list[dict[str, Any]] = [
    {
        "id": "summit_trip",
        "prompt": "Book my trip from Ostreva to Pellmoor for the Design Summit at Kessel Hall. I must arrive in Pellmoor by "
        "21:00 on 9 June 2026 and fly back to Ostreva on 12 June leaving after 17:00. Book a hotel for the nights "
        "of 9, 10 and 11 June with at least 4 stars within 2 km of Kessel Hall. Total budget EUR 900. Do not book "
        "anything that clashes with my calendar.",
        "data": {
            "constraints": {
                "flights": [
                    # The Ostreva team retro ends 15:30, so the outbound flight must leave after it.
                    {
                        "origin": "OST",
                        "destination": "PEL",
                        "arrive_by": "2026-06-09T21:00",
                        "depart_after": "2026-06-09T15:30",
                    },
                    {"origin": "PEL", "destination": "OST", "depart_after": "2026-06-12T17:00", "date": "2026-06-12"},
                ],
                "hotel": {
                    "city": "Pellmoor",
                    "check_in": "2026-06-09",
                    "nights": 3,
                    "min_stars": 4,
                    "landmark": "Kessel Hall",
                    "max_km": 2.0,
                },
                "budget": 900.0,
            }
        },
    },
    {
        "id": "varrel_morning",
        "prompt": "Book the cheapest flight from Pellmoor to Varrel on 20 June 2026 that arrives before noon. No hotel.",
        "data": {
            "constraints": {
                "flights": [
                    {
                        "origin": "PEL",
                        "destination": "VAR",
                        "arrive_by": "2026-06-20T12:00",
                        "cheapest_valid": True,
                        "date": "2026-06-20",
                    }
                ],
                "hotel": None,
            }
        },
    },
    {
        "id": "varrel_stay",
        "prompt": "Book 2 nights in Varrel from 20 June 2026 at the hotel closest to Varrel Old Town that costs at most "
        "EUR 150 per night.",
        "data": {
            "constraints": {
                "flights": [],
                "hotel": {
                    "city": "Varrel",
                    "check_in": "2026-06-20",
                    "nights": 2,
                    "max_price_per_night": 150.0,
                    "landmark": "Varrel Old Town",
                    "closest": True,
                },
            }
        },
    },
]

SYSTEM = "You are a travel booking assistant. Today is 2026-05-14. Book exactly what is needed, nothing more."


@register
class TripPlanner(Scenario):
    name = "trip_planner"
    title = "Trip planning with replanning"
    tokens_per_trial = 20000
    param_choices = {"mode": ["plan_execute", "single_loop"]}
    pattern = "planning"
    description = "Constrained trip booking with an injected sold-out failure; plan-and-execute vs single tool loop."
    roles = [
        RoleRequirement("planner", "writes and repairs the plan, writes the final summary"),
        RoleRequirement("executor", "executes plan steps with the booking tools", fallback="planner", kind="agent"),
    ]
    default_params = {"mode": "plan_execute", "max_replans": 2, "max_step_turns": 6, "max_turns": 16}
    pass_criteria = ["constraints_satisfied", "no_extra_bookings"]

    def load_tasks(self) -> list[Task]:
        return [Task.model_validate(entry) for entry in TASKS]

    def fixtures(self) -> dict[str, Any]:
        return {
            "travel.json": {"flights": FLIGHTS, "hotels": HOTELS, "calendar": CALENDAR},
            "tools.json": [t.schema() | {"permission": t.permission} for t in TravelAgency().tools()],
        }

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        agency = TravelAgency()
        registry = ToolRegistry(agency.tools())
        executor = ToolExecutor(registry, ctx.trace, role="executor")
        extras: dict[str, Any] = {"mode": ctx.params["mode"]}
        if ctx.params["mode"] == "single_loop":
            loop = await run_tool_loop(
                models.get("executor", "planner"),
                [system(SYSTEM), user(task.prompt)],
                executor,
                max_turns=ctx.params["max_turns"],
                trace=ctx.trace,
                step="loop",
                tool_step="tools",
            )
            final = loop.final
            extras["stop_reason"] = loop.stop_reason
        else:
            result = await plan_and_execute(
                models["planner"],
                models.get("executor", "planner"),
                task.prompt,
                executor,
                ctx.trace,
                validator=basic_validator(set(registry.names())),
                context=SYSTEM,
                max_replans=ctx.params["max_replans"],
                max_step_turns=ctx.params["max_step_turns"],
            )
            final = result.final
            extras.update(
                {
                    "repairs": result.repairs,
                    "replans": result.replans,
                    "aborted": result.aborted,
                    "plan_steps": [len(p.steps) for p in result.plans],
                }
            )
        return TrialOutput(
            final=final,
            env_state={
                "bookings": agency.bookings,
                "active": agency.active(),
                "failed_bookings": agency.failed_bookings,
            },
            extras=extras,
        )

    def brief(self) -> Brief:
        return Brief(
            summary="Planning with an injected failure: book flights and a hotel under hard constraints, and "
            "recover when a flight sells out at booking time.",
            environment="Mock flight, hotel and calendar services; booking the cheapest flight fails, so the plan "
            "must change.",
            criteria={"constraints_satisfied": "times, calendar, budget, hotel stars and distance, cheapest choice",
                      "no_extra_bookings": "nothing booked twice or left over"},
            measured=["plan_repairs and replans", "recovered_from_failure"],
            compare=["mode: plan_execute vs single_loop", "a strong planner with a small executor"],
        )  # fmt: skip

    def describe(self, task: Task) -> TaskView:
        c = task.data["constraints"]
        rules = [_flight_rule(f) for f in c.get("flights", [])]
        if hotel := c.get("hotel"):
            rules.append(_hotel_rule(hotel))
        if "budget" in c:
            rules.append(f"total at most ${c['budget']:.0f}")
        return TaskView(id=task.id, prompt=task.prompt, tags=task.tags, expected=[bullet("Hard constraints", rules)])

    def workflow(self) -> Workflow:
        planned = when("mode", equals="plan_execute")
        single = when("mode", equals="single_loop")
        return Workflow(
            steps=[START,
                   step("plan", "Planner writes the plan", "llm", "planner", when=planned),
                   step("validate", "Validate the plan", "check", description="dates, budget, calendar", when=planned),
                   step("execute", "Executor runs a step", "llm", "executor", when=planned),
                   step("loop", "Agent plans and books", "llm", "executor", "one tool loop, no explicit plan", single),
                   step("tools", "Flights, hotels, calendar", "tool", description="a flight sells out when booked"),
                   step("replan", "Replan after a failed step", "llm", "planner", when=planned),
                   step("synthesise", "Planner writes the answer", "llm", "planner", when=planned), END],
            edges=[edge("start", "plan"), edge("plan", "validate"), edge("validate", "plan", "rejected", loop=True),
                   edge("validate", "execute", "ok"), edge("execute", "tools", "tool call"),
                   edge("tools", "execute", "result", loop=True), edge("execute", "replan", "step failed"),
                   edge("replan", "validate", "new plan", loop=True), edge("execute", "synthesise", "all steps done"), edge("synthesise", "end"),
                   edge("start", "loop"), edge("loop", "tools", "tool call"),
                   edge("tools", "loop", "result", loop=True), edge("loop", "end", "final answer")],
        )  # fmt: skip

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [
            ToolHygieneEvaluator(),
            FunctionEvaluator("plan_quality", score_planning),
            FunctionEvaluator("trip", check_trip),
        ]


def score_planning(ctx: EvalContext) -> list[Score]:
    extras = ctx.output.extras
    scores = []
    if extras["mode"] == "plan_execute":
        scores += [
            Score(name="plan_repairs", value=float(extras["repairs"]), level="step", passed=extras["repairs"] == 0),
            Score(name="replans", value=float(extras["replans"]), level="step"),
            Score(name="plan_aborted", value=float(extras["aborted"]), level="step", passed=not extras["aborted"]),
        ]
    hit_failure = bool(ctx.output.env_state["failed_bookings"])
    if hit_failure:
        recovered = _constraint_problems(ctx) == []
        scores.append(Score(name="recovered_from_failure", value=float(recovered), level="step", passed=recovered))
    return scores


def check_trip(ctx: EvalContext) -> list[Score]:
    problems = _constraint_problems(ctx)
    constraints = ctx.task.data["constraints"]
    active = ctx.output.env_state["active"]
    expected_count = len(constraints["flights"]) + (1 if constraints["hotel"] else 0)
    extra = len(active) - expected_count
    return [
        Score(
            name="constraints_satisfied",
            value=float(not problems),
            level="e2e",
            passed=not problems,
            rationale="; ".join(problems) or "all constraints met",
        ),
        Score(
            name="no_extra_bookings",
            value=float(extra <= 0),
            level="e2e",
            passed=extra <= 0,
            rationale=f"{len(active)} active bookings, expected {expected_count}",
        ),
    ]


def _constraint_problems(ctx: EvalContext) -> list[str]:
    constraints = ctx.task.data["constraints"]
    active = ctx.output.env_state["active"]
    flights = [b for b in active if b["type"] == "flight"]
    hotels = [b for b in active if b["type"] == "hotel"]
    problems: list[str] = []
    for leg in constraints["flights"]:
        matching = [f for f in flights if f["origin"] == leg["origin"] and f["destination"] == leg["destination"]]
        if len(matching) != 1:
            problems.append(f"{len(matching)} bookings for {leg['origin']}->{leg['destination']}, expected 1")
            continue
        problems += _flight_problems(matching[0], leg)
    if spec := constraints["hotel"]:
        if len(hotels) != 1:
            problems.append(f"{len(hotels)} hotel bookings, expected 1")
        else:
            problems += _hotel_problems(hotels[0], spec)
    if "budget" in constraints:
        total = sum(b.get("price_eur", b.get("total_eur", 0.0)) for b in active)
        if total > constraints["budget"]:
            problems.append(f"total EUR {total:.0f} exceeds budget {constraints['budget']:.0f}")
    return problems


def _flight_problems(flight: dict[str, Any], leg: dict[str, Any]) -> list[str]:
    problems = []
    if "arrive_by" in leg and flight["arrives"] > leg["arrive_by"]:
        problems.append(f"{flight['flight_id']} arrives {flight['arrives']}, after {leg['arrive_by']}")
    if "depart_after" in leg and flight["departs"] < leg["depart_after"]:
        problems.append(f"{flight['flight_id']} departs {flight['departs']}, before {leg['depart_after']}")
    if "date" in leg and not flight["departs"].startswith(leg["date"]):
        problems.append(f"{flight['flight_id']} is not on {leg['date']}")
    if leg.get("cheapest_valid"):
        valid = [
            f
            for f in FLIGHTS
            if f[1] == leg["origin"]
            and f[2] == leg["destination"]
            and f[3].startswith(leg["date"])
            and f[4] <= leg["arrive_by"]
            and not f[6]
        ]
        cheapest = min(valid, key=lambda f: f[5])
        if flight["flight_id"] != cheapest[0]:
            problems.append(f"booked {flight['flight_id']}, cheapest valid option is {cheapest[0]}")
    return problems


def _hotel_problems(booking: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    hotel = next(h for h in HOTELS if h[0] == booking["hotel_id"])
    problems = []
    if hotel[1] != spec["city"]:
        problems.append(f"hotel is in {hotel[1]}")
    if booking["check_in"] != spec["check_in"] or int(booking["nights"]) != spec["nights"]:
        problems.append(
            f"hotel dates {booking['check_in']} x{booking['nights']}, expected {spec['check_in']} x{spec['nights']}"
        )
    if hotel[3] < spec.get("min_stars", 0):
        problems.append(f"{hotel[2]} has {hotel[3]} stars")
    if "max_km" in spec and hotel[5][spec["landmark"]] > spec["max_km"]:
        problems.append(f"{hotel[2]} is {hotel[5][spec['landmark']]} km from {spec['landmark']}")
    if "max_price_per_night" in spec and hotel[4] > spec["max_price_per_night"]:
        problems.append(f"{hotel[2]} costs {hotel[4]} per night")
    if spec.get("closest"):
        affordable = [
            h for h in HOTELS if h[1] == spec["city"] and h[4] <= spec.get("max_price_per_night", float("inf"))
        ]
        best = min(affordable, key=lambda h: h[5][spec["landmark"]])
        if best[0] != hotel[0]:
            problems.append(f"booked {hotel[2]}, closest eligible is {best[2]}")
    return problems


def _flight_rule(f: dict[str, Any]) -> str:
    parts = [f"flight {f['origin']}→{f['destination']}"]
    if f.get("date"):
        parts.append(f"on {f['date']}")
    if f.get("depart_after"):
        parts.append(f"departing after {f['depart_after'].replace('T', ' ')}")
    if f.get("arrive_by"):
        parts.append(f"arriving by {f['arrive_by'].replace('T', ' ')}")
    if f.get("cheapest_valid"):
        parts.append("the cheapest one that fits")
    return ", ".join(parts)


def _hotel_rule(h: dict[str, Any]) -> str:
    parts = [f"hotel in {h['city']}: {h['nights']} nights from {h['check_in']}"]
    if h.get("min_stars"):
        parts.append(f"at least {h['min_stars']}★")
    if h.get("max_price_per_night"):
        parts.append(f"at most ${h['max_price_per_night']:.0f} per night")
    if h.get("max_km"):
        parts.append(f"within {h['max_km']} km of {h['landmark']}")
    elif h.get("closest"):
        parts.append(f"the closest to {h['landmark']}")
    return ", ".join(parts)
