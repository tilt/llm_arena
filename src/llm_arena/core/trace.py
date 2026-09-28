"""Execution traces: the record step-level evaluators read.

Patterns open spans for every model call, tool call, code execution, handoff and plan. A span
keeps inputs and outputs verbatim so an evaluator can re-check a single step without rerunning
the pipeline, which is the point of component-level evaluation.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from pydantic import BaseModel, Field

from llm_arena.core.artifacts import MAX_FILE_BYTES, MAX_TRIAL_BYTES, ArtifactRef, ArtifactSink

SpanKind = Literal["llm_call", "tool_call", "code_exec", "handoff", "plan", "critique", "step", "judge", "decision"]


class Span(BaseModel):
    kind: SpanKind
    name: str
    role: str | None = None
    model: str | None = None
    input: Any = None
    output: Any = None
    error: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    started_at: float = Field(default_factory=time.time)
    duration_s: float = 0.0
    parent: int | None = None  # index of the enclosing span
    step: str | None = None  # workflow step (scenarios/workflow.py) this span belongs to
    artifacts: list[ArtifactRef] = Field(default_factory=list)  # files the step used or produced

    @property
    def ok(self) -> bool:
        return self.error is None


class Trace(BaseModel):
    spans: list[Span] = Field(default_factory=list)
    _stack: list[int] = []
    _steps: list[str] = []
    _sink: ArtifactSink | None = None
    _stored: int = 0

    def model_post_init(self, __context: Any) -> None:
        self._stack = []
        self._steps = []
        self._sink = None
        self._stored = 0

    def store_artifacts_with(self, sink: ArtifactSink | None) -> None:
        """The runner connects the trial's store; without one, attachments are listed but not kept."""
        self._sink = sink

    def attach(self, span: Span, name: str, data: bytes, media_type: str) -> ArtifactRef:
        """Keep a file with the span that used or produced it (within the size caps)."""
        size = len(data)
        if self._sink is None:
            ref = ArtifactRef(name=name, media_type=media_type, size=size, note="not stored (no artifact store)")
        elif size > MAX_FILE_BYTES or self._stored + size > MAX_TRIAL_BYTES:
            ref = ArtifactRef(name=name, media_type=media_type, size=size, note="not stored (size limit)")
        else:
            ref = self._sink(name, data, media_type)
            self._stored += size
        span.artifacts.append(ref)
        return ref

    def add(self, span: Span) -> Span:
        if span.parent is None and self._stack:
            span.parent = self._stack[-1]
        if span.step is None and self._steps:
            span.step = self._steps[-1]
        self.spans.append(span)
        return span

    @contextmanager
    def span(self, kind: SpanKind, name: str, **fields: Any) -> Iterator[Span]:
        """Open a span; nested spans get it as parent. Exceptions are recorded and re-raised."""
        current = self.add(Span(kind=kind, name=name, **fields))
        self._stack.append(len(self.spans) - 1)
        started = time.perf_counter()
        try:
            yield current
        except Exception as exc:
            current.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            current.duration_s = time.perf_counter() - started
            self._stack.pop()

    @contextmanager
    def in_step(self, step: str | None) -> Iterator[None]:
        """Spans opened inside belong to this workflow step (the innermost step wins; None inherits)."""
        if step is None:
            yield
            return
        self._steps.append(step)
        try:
            yield
        finally:
            self._steps.pop()

    def select(self, kind: SpanKind | None = None, name: str | None = None, role: str | None = None) -> list[Span]:
        return [
            span
            for span in self.spans
            if (kind is None or span.kind == kind)
            and (name is None or span.name == name)
            and (role is None or span.role == role)
        ]

    def totals(self) -> dict[str, float]:
        llm_spans = self.select("llm_call")
        external = sum(s.attrs.get("external_cost_usd", 0.0) for s in self.select("decision"))
        return {
            "llm_calls": len(llm_spans),
            "tool_calls": len(self.select("tool_call")),
            "prompt_tokens": sum(s.prompt_tokens for s in llm_spans),
            "completion_tokens": sum(s.completion_tokens for s in llm_spans),
            "cost_usd": sum(s.cost_usd for s in llm_spans) + external,  # + non-LLM decision services (Jev)
            "llm_latency_s": sum(s.duration_s for s in llm_spans),
        }
