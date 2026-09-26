"""Typed tools: a Python function becomes a JSON-schema tool via its signature.

Describe parameters with `Annotated[type, Field(description=...)]`; the docstring's first
paragraph is the tool description. Tools are usually built per trial by a factory that closes
over the trial's mock environment (mailbox, shop DB, …), so trials never share state.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, get_type_hints, overload

from pydantic import BaseModel, ConfigDict, create_model

Permission = Literal["read", "write", "destructive"]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    params_model: type[BaseModel]
    permission: Permission = "read"

    def schema(self) -> dict[str, Any]:
        parameters = self.params_model.model_json_schema()
        parameters.pop("title", None)
        for prop in parameters.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": parameters},
        }


@overload
def tool(fn: Callable[..., Any], *, name: str | None = None, permission: Permission = "read") -> Tool: ...


@overload
def tool(
    fn: None = None, *, name: str | None = None, permission: Permission = "read"
) -> Callable[[Callable[..., Any]], Tool]: ...


def tool(
    fn: Callable[..., Any] | None = None, *, name: str | None = None, permission: Permission = "read"
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """Decorator (bare or with arguments) turning a function into a Tool."""

    def build(function: Callable[..., Any]) -> Tool:
        return Tool(
            name=name or function.__name__,
            description=_first_paragraph(function.__doc__ or function.__name__),
            fn=function,
            params_model=_params_model(function),
            permission=permission,
        )

    return build(fn) if fn is not None else build


def _first_paragraph(doc: str) -> str:
    return inspect.cleandoc(doc).split("\n\n", 1)[0].replace("\n", " ").strip()


def _params_model(function: Callable[..., Any]) -> type[BaseModel]:
    hints = get_type_hints(function, include_extras=True)
    fields: dict[str, Any] = {}
    for parameter in inspect.signature(function).parameters.values():
        annotation = hints.get(parameter.name, Any)
        default = ... if parameter.default is inspect.Parameter.empty else parameter.default
        fields[parameter.name] = (annotation, default)
    # extra="forbid": hallucinated argument names are an error we want to count, not ignore.
    return create_model(
        f"{function.__name__}_params",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for item in tools:
            self.add(item)

    def add(self, item: Tool) -> None:
        if item.name in self._tools:
            raise ValueError(f"duplicate tool name {item.name!r}")
        self._tools[item.name] = item

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [item.schema() for item in self._tools.values()]

    def subset(self, names: Iterable[str]) -> ToolRegistry:
        wanted = set(names)
        return ToolRegistry(item for item in self._tools.values() if item.name in wanted)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
