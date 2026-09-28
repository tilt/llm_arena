"""Declarative description of a scenario's agentic workflow, for UIs and documentation.

A workflow is a small graph: steps (model calls, tool or code execution, checks, control
decisions, a human approver) and transitions. A model step names the *role* it runs on, which is
what a config binds to a model, so a UI can show "this step runs on that model". Steps and
transitions may depend on parameters (`when`): the reflection loop exists only with
`reflection_rounds > 0`, the ReAct tool loop only for `variant != cot`. Control policies appear as
the pseudo-parameter `control` (agent | gate | policy | review) and `review` (bool).

The workflow documents the code in `run()`; it does not drive it. Tests check that every role a
scenario declares appears in its workflow and that every referenced parameter exists.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

StepKind = Literal["start", "end", "llm", "tool", "code", "check", "decision", "human"]
CONTROL_PARAM = "control"  # pseudo-parameter: who makes control decisions (from PipelineConfig.decisions)
REVIEW_PARAM = "review"  # pseudo-parameter: post-run trace review by the control policy


class Condition(BaseModel):
    """True when the parameter matches: `equals` / `one_of` / `gt` (all given ones must hold)."""

    param: str
    equals: Any = None
    one_of: list[Any] | None = None
    gt: float | None = None

    def holds(self, params: dict[str, Any]) -> bool:
        value = params.get(self.param)
        if self.equals is not None and value != self.equals:
            return False
        if self.one_of is not None and value not in self.one_of:
            return False
        return not (self.gt is not None and not (isinstance(value, int | float) and value > self.gt))


class WorkflowStep(BaseModel):
    id: str
    label: str
    kind: StepKind
    role: str | None = Field(default=None, description="role whose model runs this step (model and decision steps)")
    also: list[str] = Field(default_factory=list, description="further roles the step may call (e.g. a fallback)")
    description: str = ""
    when: list[Condition] = Field(default_factory=list)


class WorkflowEdge(BaseModel):
    source: str
    target: str
    label: str = ""
    loop: bool = Field(default=False, description="goes back to an earlier step (drawn as a return arc)")
    when: list[Condition] = Field(default_factory=list)
    unless: str | None = Field(default=None, description="dropped when this step is part of the resolved workflow")


class Workflow(BaseModel):
    steps: list[WorkflowStep]
    edges: list[WorkflowEdge]

    def resolve(self, params: dict[str, Any]) -> Workflow:
        """The workflow as it runs with these parameters (unmet `when` conditions removed)."""
        steps = [s for s in self.steps if all(c.holds(params) for c in s.when)]
        kept = {s.id for s in steps}
        edges = [
            e
            for e in self.edges
            if e.source in kept and e.target in kept and e.unless not in kept and all(c.holds(params) for c in e.when)
        ]
        return Workflow(steps=steps, edges=edges)

    def roles(self) -> set[str]:
        return {role for s in self.steps for role in ([s.role] if s.role else []) + s.also}

    def params(self) -> set[str]:
        conditions = [c for s in self.steps for c in s.when] + [c for e in self.edges for c in e.when]
        return {c.param for c in conditions}


# ---- builders --------------------------------------------------------------------------------------
def step(id: str, label: str, kind: StepKind, role: str | None = None, description: str = "",
         when: list[Condition] | None = None) -> WorkflowStep:  # fmt: skip
    return WorkflowStep(id=id, label=label, kind=kind, role=role, description=description, when=when or [])


def edge(source: str, target: str, label: str = "", *, loop: bool = False,
         when: list[Condition] | None = None, unless: str | None = None) -> WorkflowEdge:  # fmt: skip
    return WorkflowEdge(source=source, target=target, label=label, loop=loop, when=when or [], unless=unless)


def when(param: str, *, equals: Any = None, in_: list[Any] | None = None, gt: float | None = None) -> list[Condition]:
    return [Condition(param=param, equals=equals, one_of=in_, gt=gt)]


START = step("start", "Task", "start")
END = step("end", "Result", "end", description="scored by the scenario's evaluators")


def reflection(*, generator: str, critic: str, draft: str, critique: str, revise: str,
               execute: WorkflowStep | None = None, evidence: str = "") -> Workflow:  # fmt: skip
    """draft → (execute) → critique ⇄ revise, for `reflection_rounds` rounds or until the critic accepts."""
    rounds = when("reflection_rounds", gt=0)
    no_rounds = when("reflection_rounds", equals=0)
    after_draft = execute.id if execute else "draft"
    steps = [START, step("draft", draft, "llm", generator)]
    edges = [edge("start", "draft")]
    if execute:
        steps.append(execute)
        edges.append(edge("draft", execute.id))
    steps += [
        step("critique", critique, "llm", critic, "accept, or list issues", rounds),
        step("revise", revise, "llm", generator, "rewrite using the critic's issues", rounds),
        END,
    ]
    edges += [
        edge(after_draft, "critique", evidence, when=rounds),
        edge("critique", "revise", "revise", when=rounds),
        edge("revise", after_draft if execute else "critique", "next round", loop=True, when=rounds),
        edge("critique", "end", "accept / rounds used", when=rounds),
        edge(after_draft, "end", when=no_rounds),
    ]
    return Workflow(steps=steps, edges=edges)


def tool_agent(*, role: str = "agent", tools: str = "tools", controlled: bool = False) -> Workflow:
    """The agent's tool loop; with `controlled`, the control-policy variants (gate, policy, review)."""
    if not controlled:
        return Workflow(
            steps=[START, step("agent", "Agent picks a tool", "llm", role), step("tools", tools, "tool"), END],
            edges=[edge("start", "agent"), edge("agent", "tools", "tool call"),
                   edge("tools", "agent", "result", loop=True), edge("agent", "end", "final answer")],
        )  # fmt: skip
    agent_loop = when(CONTROL_PARAM, in_=["agent", "gate", "review"])
    gated = when(CONTROL_PARAM, in_=["gate", "policy"])
    policy = when(CONTROL_PARAM, equals="policy")
    ungated = when(CONTROL_PARAM, in_=["agent", "review"])
    reviewed = [*when(CONTROL_PARAM, in_=["gate", "policy", "review"]), *when(REVIEW_PARAM, equals=True)]
    steps = [
        START,
        step("agent", "Agent picks a tool", "llm", role, "the agent decides everything itself", agent_loop),
        step("decide", "Policy: next action? complete?", "decision", "decider",
             "choice over the tools + finish; task complete (yes/no)", policy).model_copy(update={"also": ["escalation"]}),
        step("args", "Agent fills in the arguments", "llm", role, "only the tool the policy chose", policy),
        step("approval", "Policy: needs approval?", "decision", "decider",
             "state-changing actions only; scored against the approval oracle", gated).model_copy(
            update={"also": ["escalation"]}),
        step("human", "Human approver (oracle)", "human", description="approves exactly the compliant actions", when=gated),
        step("tools", tools, "tool"),
        step("reply", "Agent writes the final reply", "llm", role, when=policy),
        step("review", "Policy: trace review", "decision", "decider", "task accomplished? needs human review?",
             reviewed).model_copy(update={"also": ["escalation"]}),
        END,
    ]  # fmt: skip
    edges = [
        edge("start", "agent", when=agent_loop), edge("start", "decide", when=policy),
        edge("agent", "tools", "read / write", when=ungated),
        edge("agent", "approval", "write", when=when(CONTROL_PARAM, equals="gate")),
        edge("agent", "tools", "read", when=when(CONTROL_PARAM, equals="gate")),
        edge("decide", "args", "tool"), edge("args", "tools", "read"), edge("args", "approval", "write"),
        edge("approval", "tools", "no approval needed"), edge("approval", "human", "needs approval"),
        edge("human", "tools", "approved"),
        edge("human", "agent", "rejected", loop=True, when=agent_loop),
        edge("human", "decide", "rejected", loop=True, when=policy),
        edge("tools", "agent", "result", loop=True, when=agent_loop),
        edge("tools", "decide", "result", loop=True, when=policy),
        edge("decide", "reply", "finish"),
        edge("agent", "review", "final answer", when=reviewed), edge("reply", "review", when=reviewed),
        edge("agent", "end", "final answer", unless="review"), edge("reply", "end", unless="review"),
        edge("review", "end"),
    ]  # fmt: skip
    return Workflow(steps=steps, edges=edges)


def single_call(role: str = "model", label: str = "Model answers", check: str = "Grader") -> Workflow:
    return Workflow(
        steps=[START, step("answer", label, "llm", role), step("grade", check, "check"), END],
        edges=[edge("start", "answer"), edge("answer", "grade"), edge("grade", "end")],
    )
