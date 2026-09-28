"""Every scenario's declared workflow matches its roles and parameters, and stays connected for all settings."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

import llm_arena.benchmarks  # noqa: F401
import llm_arena.scenarios.catalog  # noqa: F401
from llm_arena.scenarios.base import SCENARIOS, get_scenario
from llm_arena.scenarios.workflow import CONTROL_PARAM, REVIEW_PARAM, Workflow

CONTROLS = ["agent", "gate", "policy", "review"]


def settings(name: str) -> list[dict[str, Any]]:
    """Every combination of the parameters the workflow depends on."""
    scenario = get_scenario(name)
    axes: dict[str, list[Any]] = {}
    for param in scenario.workflow().params():
        if param == CONTROL_PARAM:
            axes[param] = CONTROLS
        elif param == REVIEW_PARAM:
            axes[param] = [True, False]
        elif param in scenario.param_choices:
            axes[param] = scenario.param_choices[param]
        elif isinstance(scenario.default_params[param], bool):
            axes[param] = [True, False]
        else:
            axes[param] = [0, 1, 2]
    base = {**scenario.default_params, CONTROL_PARAM: "agent", REVIEW_PARAM: True}
    return [{**base, **dict(zip(axes, combo, strict=True))} for combo in itertools.product(*axes.values())]


def reachable(flow: Workflow, start: str, reverse: bool = False) -> set[str]:
    seen, frontier = {start}, [start]
    while frontier:
        node = frontier.pop()
        for e in flow.edges:
            a, b = (e.target, e.source) if reverse else (e.source, e.target)
            if a == node and b not in seen:
                seen.add(b)
                frontier.append(b)
    return seen


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_workflow_names_every_role_and_only_known_params(name: str) -> None:
    scenario = get_scenario(name)
    flow = scenario.workflow()
    assert flow.roles() == {r.name for r in scenario.roles}
    known = set(scenario.default_params) | ({CONTROL_PARAM, REVIEW_PARAM} if scenario.supports_decisions else set())
    assert flow.params() <= known
    ids = [s.id for s in flow.steps]
    assert len(ids) == len(set(ids)) and {"start", "end"} <= set(ids)
    assert all(e.source in ids and e.target in ids for e in flow.edges)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_setting_gives_a_connected_workflow(name: str) -> None:
    for params in settings(name):
        flow = get_scenario(name).workflow().resolve(params)
        ids = {s.id for s in flow.steps}
        assert reachable(flow, "start") == ids, (name, params, ids - reachable(flow, "start"))
        assert reachable(flow, "end", reverse=True) == ids, (name, params, ids - reachable(flow, "end", reverse=True))


def test_resolution_follows_parameters() -> None:
    flow = get_scenario("reflection_sql").workflow()
    assert "critique" not in {s.id for s in flow.resolve({"reflection_rounds": 0, "feedback": "execution"}).steps}
    labels = {e.label for e in flow.resolve({"reflection_rounds": 1, "feedback": "sql_only"}).edges}
    assert "SQL only" in labels and "SQL + result" not in labels
    desk = get_scenario("support_desk").workflow()
    agent = {s.id for s in desk.resolve({CONTROL_PARAM: "agent", REVIEW_PARAM: True}).steps}
    policy = {s.id for s in desk.resolve({CONTROL_PARAM: "policy", REVIEW_PARAM: True}).steps}
    assert "decide" not in agent and "review" not in agent
    assert {"decide", "args", "approval", "human", "reply", "review"} <= policy and "agent" not in policy
