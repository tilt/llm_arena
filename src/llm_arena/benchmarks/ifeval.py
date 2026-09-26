"""IFEval subset (Apache-2.0 data) with our own implementation of the verifiable-instruction checkers.

Only items whose instructions are all supported below are used (language detection is left
out to avoid a dependency). Scores: prompt-level strict accuracy and instruction-level accuracy.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from llm_arena.benchmarks.base import Benchmark, correct_score
from llm_arena.benchmarks.hf import IFEVAL, load_rows, stratified_sample
from llm_arena.eval.base import EvalContext, Score, Task
from llm_arena.scenarios.base import register

Checker = Callable[[str, dict[str, Any]], bool]


def _compare(actual: int, relation: str | None, target: int) -> bool:
    return actual < target if relation == "less than" else actual >= target


def _words(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text)


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def _json(text: str) -> bool:
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True


CHECKERS: dict[str, Checker] = {
    "punctuation:no_comma": lambda t, k: "," not in t,
    "length_constraints:number_words": lambda t, k: _compare(len(_words(t)), k.get("relation"), k["num_words"]),
    "length_constraints:number_sentences": lambda t, k: _compare(_sentences(t), k.get("relation"), k["num_sentences"]),
    "length_constraints:number_paragraphs": lambda t, k: (
        len([p for p in re.split(r"\s*\*\*\*\s*", t) if p.strip()]) == k["num_paragraphs"]
    ),
    "detectable_format:number_bullet_lists": lambda t, k: (
        len(re.findall(r"^\s*[*-]\s", t, re.MULTILINE)) == k["num_bullets"]
    ),
    "detectable_format:title": lambda t, k: bool(re.search(r"<<[^\n]+>>", t)),
    "detectable_format:json_format": lambda t, k: _json(t),
    "detectable_format:number_highlighted_sections": lambda t, k: (
        len(re.findall(r"\*[^\n*]+\*", t)) >= k["num_highlights"]
    ),
    "detectable_format:multiple_sections": lambda t, k: (
        len(re.findall(rf"{re.escape(k['section_spliter'])}\s*\d+", t)) >= k["num_sections"]
    ),
    "change_case:english_lowercase": lambda t, k: t == t.lower() and any(c.isalpha() for c in t),
    "change_case:english_capital": lambda t, k: t == t.upper() and any(c.isalpha() for c in t),
    "change_case:capital_word_frequency": lambda t, k: _compare(
        len([w for w in _words(t) if w.isupper()]), k.get("capital_relation"), k["capital_frequency"]
    ),
    "startend:end_checker": lambda t, k: t.strip().strip("\"'`").endswith(k["end_phrase"].strip()),
    "startend:quotation": lambda t, k: t.strip().startswith('"') and t.strip().endswith('"'),
    "keywords:existence": lambda t, k: all(w.lower() in t.lower() for w in k["keywords"]),
    "keywords:forbidden_words": lambda t, k: (
        not any(re.search(rf"\b{re.escape(w)}\b", t, re.IGNORECASE) for w in k["forbidden_words"])
    ),
    "keywords:frequency": lambda t, k: _compare(
        len(re.findall(rf"\b{re.escape(k['keyword'])}\b", t, re.IGNORECASE)), k.get("relation"), k["frequency"]
    ),
    "keywords:letter_frequency": lambda t, k: _compare(
        t.lower().count(k["letter"].lower()), k.get("let_relation"), k["let_frequency"]
    ),
    "detectable_content:postscript": lambda t, k: k["postscript_marker"] in t,
    "detectable_content:number_placeholders": lambda t, k: len(re.findall(r"\[[^\]]+\]", t)) >= k["num_placeholders"],
    "combination:repeat_prompt": lambda t, k: t.strip().lower().startswith(k["prompt_to_repeat"].strip().lower()),
    "combination:two_responses": lambda t, k: len([p for p in t.split("******") if p.strip()]) == 2,
    "detectable_format:constrained_response": lambda t, k: any(
        option in t for option in ("My answer is yes.", "My answer is no.", "My answer is maybe.")
    ),
    "length_constraints:nth_paragraph_first_word": lambda t, k: _nth_paragraph_starts_with(t, k),
}


def _nth_paragraph_starts_with(text: str, kwargs: dict[str, Any]) -> bool:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    index = kwargs["nth_paragraph"] - 1
    if len(paragraphs) != kwargs["num_paragraphs"] or index >= len(paragraphs):
        return False
    first = re.sub(r"[^\w]", "", paragraphs[index].split()[0]).lower() if paragraphs[index].split() else ""
    return bool(first == str(kwargs["first_word"]).lower())


@register
class IFEvalBench(Benchmark):
    name = "ifeval"
    title = "IFEval (instruction following)"
    tokens_per_trial = 900
    description = "IFEval subset (Apache-2.0): verifiable formatting/length/keyword instructions, own checkers."
    sample_size = 100
    pass_criteria = ["correct"]

    def load_tasks(self) -> list[Task]:
        supported = [row for row in load_rows(IFEVAL) if all(i in CHECKERS for i in row["instruction_id_list"])]
        rows = stratified_sample(supported, self.sample_size, key=lambda row: row["instruction_id_list"][0], seed=0)
        return [
            Task(
                id=f"ifeval-{row['key']}",
                prompt=row["prompt"],
                data={
                    "instructions": row["instruction_id_list"],
                    "kwargs": [{k: v for k, v in kw.items() if v is not None} for kw in row["kwargs"]],
                },
                tags=list(row["instruction_id_list"]),
            )
            for row in rows
        ]

    async def grade(self, ctx: EvalContext) -> list[Score]:
        results = [
            (instruction, CHECKERS[instruction](ctx.output.final, kwargs))
            for instruction, kwargs in zip(ctx.task.data["instructions"], ctx.task.data["kwargs"], strict=True)
        ]
        followed = sum(ok for _, ok in results)
        failed = [instruction for instruction, ok in results if not ok]
        return [
            correct_score(not failed, f"failed: {failed}" if failed else "all instructions followed"),
            Score(name="instruction_accuracy", value=followed / len(results), level="e2e"),
        ]
