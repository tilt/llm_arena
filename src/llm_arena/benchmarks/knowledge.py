"""GSM8K (grade-school maths) and MMLU-Pro (10-option knowledge/reasoning) subsets."""

from __future__ import annotations

import re

from llm_arena.benchmarks.base import Benchmark, answer_line, correct_score
from llm_arena.benchmarks.hf import GSM8K, MMLU_PRO, load_rows, stratified_sample
from llm_arena.eval.base import EvalContext, Score, Task
from llm_arena.eval.compare import first_number, last_number, numbers_match
from llm_arena.scenarios.base import register

LETTERS = "ABCDEFGHIJ"


@register
class GSM8KBench(Benchmark):
    name = "gsm8k"
    sources = (GSM8K,)
    title = "GSM8K (maths word problems)"
    tokens_per_trial = 800
    description = "GSM8K test subset (MIT): multi-step arithmetic word problems, numeric match."
    sample_size = 100

    def load_tasks(self) -> list[Task]:
        rows = stratified_sample(load_rows(GSM8K), self.sample_size, seed=0)
        return [
            Task(
                id=f"gsm8k-{index}",
                prompt=f"{row['question']}\n\nSolve step by step. End with a final line 'Answer: <number>'.",
                data={"answer": float(row["answer"].split("####")[-1].strip().replace(",", ""))},
            )
            for index, row in enumerate(rows)
        ]

    async def grade(self, ctx: EvalContext) -> list[Score]:
        # The number right after "Answer:" wins; without that line, fall back to the last number in the text.
        line = answer_line(ctx.output.final)
        predicted = first_number(line) if line else last_number(ctx.output.final)
        return [
            correct_score(
                numbers_match(predicted, ctx.task.data["answer"]), f"pred={predicted} gold={ctx.task.data['answer']}"
            )
        ]


_CHOICE = re.compile(r"\(?\b([A-J])\b\)?")


def parse_choice(text: str) -> str | None:
    line = answer_line(text)
    if line and (match := _CHOICE.search(line)):
        return match.group(1)
    matches = re.findall(r"answer is \(?([A-J])\)?", text, re.IGNORECASE)
    return matches[-1].upper() if matches else None


@register
class MMLUProBench(Benchmark):
    name = "mmlu_pro"
    sources = (MMLU_PRO,)
    title = "MMLU-Pro (knowledge)"
    tokens_per_trial = 1200
    description = "MMLU-Pro test subset (MIT), stratified by subject; 10-option multiple choice."
    sample_size = 140  # 10 per subject

    def load_tasks(self) -> list[Task]:
        rows = stratified_sample(load_rows(MMLU_PRO), self.sample_size, key=lambda row: str(row["category"]), seed=0)
        tasks = []
        for row in rows:
            options = "\n".join(f"{LETTERS[i]}. {option}" for i, option in enumerate(row["options"]))
            tasks.append(
                Task(
                    id=f"mmlupro-{row['question_id']}",
                    prompt=f"{row['question']}\n\n{options}\n\nThink it through, then end with 'Answer: <letter>'.",
                    data={"answer": row["answer"]},
                    tags=[str(row["category"])],
                )
            )
        return tasks

    async def grade(self, ctx: EvalContext) -> list[Score]:
        choice = parse_choice(ctx.output.final)
        return [correct_score(choice == ctx.task.data["answer"], f"pred={choice} gold={ctx.task.data['answer']}")]
