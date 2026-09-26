"""Lenient JSON extraction from model text (code fences, leading prose, trailing chatter)."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Return the first JSON value found in `text`, or raise ValueError.

    Tries, in order: the whole string, fenced blocks, then the first balanced {...} or [...].
    """
    candidates = [text.strip(), *(block.strip() for block in _FENCE.findall(text))]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    for opener, closer in (("{", "}"), ("[", "]")):
        snippet = _balanced(text, opener, closer)
        if snippet is not None:
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON value found in model output")


def _balanced(text: str, opener: str, closer: str) -> str | None:
    start = text.find(opener)
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find(opener, start + 1)
    return None
