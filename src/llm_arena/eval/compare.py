"""Tolerant comparison helpers: result sets, numbers, short answers."""

from __future__ import annotations

import re
import string
from collections import Counter
from collections.abc import Sequence
from typing import Any


def _norm_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return round(float(value), 2)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return round(float(stripped), 2)
        except ValueError:
            return stripped.lower()
    return value


def result_columns_cover(gold: Sequence[Sequence[Any]], predicted: Sequence[Sequence[Any]]) -> bool:
    """True when every gold column appears (as a multiset of values) among the predicted columns.

    Row order and extra predicted columns are ignored: "which category earned most" may come
    back with or without the revenue column, and either answers the question.
    """
    if len(gold) != len(predicted):
        return False
    if not gold:
        return True
    gold_columns = [Counter(_norm_value(row[i]) for row in gold) for i in range(len(gold[0]))]
    predicted_columns = [Counter(_norm_value(row[i]) for row in predicted) for i in range(len(predicted[0]))]
    return all(column in predicted_columns for column in gold_columns)


_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def last_number(text: str) -> float | None:
    return _nth_number(text, -1)


def first_number(text: str) -> float | None:
    return _nth_number(text, 0)


def _nth_number(text: str, index: int) -> float | None:
    matches = _NUMBER.findall(text.replace("$", "").replace("€", ""))
    if not matches:
        return None
    try:
        return float(matches[index].replace(",", ""))
    except ValueError:
        return None


def numbers_match(a: float | None, b: float | None, *, rel_tol: float = 1e-4, abs_tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def normalize_answer(text: str) -> str:
    text = text.lower().strip()
    text = "".join(char for char in text if char not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def token_f1(prediction: str, gold: str) -> float:
    predicted_tokens = normalize_answer(prediction).split()
    gold_tokens = normalize_answer(gold).split()
    common = Counter(predicted_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if not predicted_tokens or not gold_tokens or overlap == 0:
        return 0.0
    precision, recall = overlap / len(predicted_tokens), overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)
