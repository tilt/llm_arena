"""How a pipeline config chooses its control policy, and the per-trial factory scenarios call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from llm_arena.core.errors import ConfigError
from llm_arena.core.trace import Trace
from llm_arena.decisions.llm_policy import LLMDecisionPolicy
from llm_arena.decisions.policy import CascadePolicy, DecisionPolicy, Rule, RulePolicy
from llm_arena.decisions.tracing import TracedPolicy
from llm_arena.llm.client import LLMClient
from llm_arena.runner.budget import BudgetGuard

PolicyKind = Literal["llm", "rules", "cascade", "jev", "ollaya"]
Stage = Literal["llm", "jev", "ollaya"]
# "System One" decision services with the same API (POST /v1/systemone): TypeSafe's hosted Jev, or decision models
# such as winnow served locally by Ollaya.
Service = Literal["jev", "ollaya"]
SERVICES: tuple[Service, ...] = ("jev", "ollaya")
ServiceFactory = Callable[[Service, str], DecisionPolicy]  # (service, model) -> policy; supplied by the runtime

DECIDER_ROLE = "decider"  # the LLM answering control questions (defaults to the agent's model)
ESCALATION_ROLE = "escalation"  # the cascade's fallback LLM (defaults to the decider)


class DecisionConfig(BaseModel):
    """Control policy of a pipeline config. Without it the agent decides everything inside its own loop."""

    policy: PolicyKind = "llm"
    control: Literal["policy", "gate", "review"] = Field(
        default="policy",
        description="policy: the policy picks each next tool, judges completion and gates state-changing actions; "
        "gate: the agent loop runs as usual and the policy only gates state-changing actions; review: the agent "
        "runs unchanged and the policy only reviews the finished trace",
    )
    primary: Stage = Field(default="llm", description="cascade: first stage")
    fallback: Stage | None = Field(default="llm", description="cascade: stage for uncertain answers (None: no stage)")
    hard_rules: bool = Field(default=True, description="cascade: the scenario's rules answer first where they apply")
    threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="cascade: escalate below this confidence")
    thresholds: dict[str, float] = Field(default_factory=dict, description="per-question thresholds")
    jev_model: str = "jev-latest"
    ollaya_model: str = Field(default="winnow:e4b", description="decision model served by the local Ollaya app")
    review: bool = Field(default=True, description="classify the finished trace (task done? needs human review?)")

    def services(self) -> set[Service]:
        """Decision services this config calls (to check availability before a run)."""
        stages = {self.primary, self.fallback} if self.policy == "cascade" else {self.policy}
        return {stage for stage in SERVICES if stage in stages}

    def llm_roles(self) -> set[str]:
        """Roles whose models this policy calls (the others are bound only by fallback and stay unused)."""
        if self.policy == "llm":
            return {DECIDER_ROLE}
        if self.policy != "cascade":
            return set()
        roles = {DECIDER_ROLE} if self.primary == "llm" else set()
        return roles | ({ESCALATION_ROLE} if self.fallback == "llm" else set())

    def service_model(self, service: Service) -> str:
        return self.jev_model if service == "jev" else self.ollaya_model


@dataclass
class DecisionSetup:
    """Handed to a scenario through RunContext; the scenario adds rules bound to its environment."""

    config: DecisionConfig
    trace: Trace
    decider: LLMClient | None = None
    escalation: LLMClient | None = None
    services: ServiceFactory | None = None
    budget: BudgetGuard | None = None

    def policy(self, rules: dict[str, Rule] | None = None) -> TracedPolicy:
        return TracedPolicy(self._build(rules or {}), self.trace, self.budget)

    def _build(self, rules: dict[str, Rule]) -> DecisionPolicy:
        kind = self.config.policy
        if kind == "rules":
            return RulePolicy(rules)
        if kind != "cascade":
            return self._stage(kind, self.decider)
        fallback = self._stage(self.config.fallback, self.escalation) if self.config.fallback else None
        return CascadePolicy(
            self._stage(self.config.primary, self.decider),
            fallback,
            hard_rules=RulePolicy(rules) if self.config.hard_rules and rules else None,
            threshold=self.config.threshold,
            thresholds=self.config.thresholds,
        )

    def _stage(self, stage: Stage | PolicyKind, client: LLMClient | None) -> DecisionPolicy:
        if stage in SERVICES:
            if self.services is None:
                raise ConfigError(f"{stage} needs the local app or CLI (not reachable from the browser)")
            return self.services(stage, self.config.service_model(stage))
        if client is None:
            raise ConfigError(f"an LLM decision policy needs a model for role {DECIDER_ROLE!r}")
        return LLMDecisionPolicy(client)
