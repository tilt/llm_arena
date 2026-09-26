"""Scenario: text-to-SQL with reflection grounded in execution feedback.

generator writes SQL → we execute it → critic reviews SQL *and its result* (or SQL only, to
measure what execution feedback adds) → generator revises. Gold answers are result sets from
hand-written gold SQL over the seeded Veloria Bikes database.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.eval.compare import result_columns_cover
from llm_arena.llm.client import system, user
from llm_arena.mocks.bikeshare import build_database, schema_text
from llm_arena.mocks.sqlite_exec import QueryResult, run_query
from llm_arena.patterns.reflection import Critique, llm_critique, reflect
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario, register, work_dir

# (id, question, gold SQL). Gold SQL is the reference; any query producing the same columns passes.
QUESTIONS: list[tuple[str, str, str]] = [
    (
        "net_revenue_by_category",
        "Which bike category earned the most net rental revenue (rental fees minus refunds), and how much in euros?",
        """SELECT b.category, ROUND(SUM(l.amount_cents) / 100.0, 2) AS net_eur
           FROM ledger l JOIN rentals r ON r.rental_id = l.rental_id JOIN bikes b ON b.bike_id = r.bike_id
           WHERE l.entry_type IN ('rental_fee', 'refund')
           GROUP BY b.category ORDER BY net_eur DESC LIMIT 1""",
    ),
    (
        "harborview_march_rentals",
        "How many rentals started at stations in Harborview during March 2026?",
        """SELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id
           WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'""",
    ),
    (
        "ebike_avg_minutes",
        "What is the average rental duration in minutes for e-bikes, rounded to one decimal?",
        """SELECT ROUND(AVG((julianday(r.ended_at) - julianday(r.started_at)) * 24 * 60), 1)
           FROM rentals r JOIN bikes b ON b.bike_id = r.bike_id WHERE b.category = 'e-bike'""",
    ),
    (
        "busiest_end_station",
        "Which station name is the destination of the most rentals?",
        """SELECT s.name FROM rentals r JOIN stations s ON s.station_id = r.end_station_id
           GROUP BY s.station_id ORDER BY COUNT(*) DESC LIMIT 1""",
    ),
    (
        "total_refunds",
        "How much money was refunded in total, in euros, as a positive number?",
        "SELECT ROUND(-SUM(amount_cents) / 100.0, 2) FROM ledger WHERE entry_type = 'refund'",
    ),
    (
        "never_rented",
        "List the ids of bikes that were never rented.",
        "SELECT bike_id FROM bikes WHERE bike_id NOT IN (SELECT bike_id FROM rentals) ORDER BY bike_id",
    ),
    (
        "net_revenue_by_city",
        "For each city, what was the net rental revenue in euros (rental fees minus refunds), attributed to the "
        "city where the rental started?",
        """SELECT s.city, ROUND(SUM(l.amount_cents) / 100.0, 2) AS net_eur
           FROM ledger l JOIN rentals r ON r.rental_id = l.rental_id JOIN stations s ON s.station_id = r.start_station_id
           WHERE l.entry_type IN ('rental_fee', 'refund') GROUP BY s.city""",
    ),
    (
        "long_rental_share",
        "What percentage of rentals lasted longer than two hours? Round to one decimal.",
        """SELECT ROUND(100.0 * SUM(CASE WHEN (julianday(ended_at) - julianday(started_at)) * 24 > 2 THEN 1 ELSE 0 END)
           / COUNT(*), 1) FROM rentals""",
    ),
    (
        "damage_fee_month",
        "In which month of 2026 (as YYYY-MM) were the highest total damage fees booked?",
        """SELECT substr(booked_at, 1, 7) AS month FROM ledger WHERE entry_type = 'damage_fee'
           GROUP BY month ORDER BY SUM(amount_cents) DESC LIMIT 1""",
    ),
    (
        "top_customer",
        "Which customer (name) paid the most in rental fees net of refunds?",
        """SELECT c.name FROM ledger l JOIN rentals r ON r.rental_id = l.rental_id
           JOIN customers c ON c.customer_id = r.customer_id WHERE l.entry_type IN ('rental_fee', 'refund')
           GROUP BY c.customer_id ORDER BY SUM(l.amount_cents) DESC LIMIT 1""",
    ),
]

_SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    blocks = _SQL_BLOCK.findall(text)
    return (blocks[-1] if blocks else text).strip().rstrip(";")


def database() -> Path:
    path = work_dir() / "veloria_bikes.sqlite"
    if not path.exists():
        build_database(path)
    return path


@register
class ReflectionSQL(Scenario):
    name = "reflection_sql"
    title = "Text-to-SQL with execution feedback"
    tokens_per_trial = 2500
    param_choices = {"feedback": ["execution", "sql_only"]}
    pattern = "reflection"
    description = "Text-to-SQL; the critic reviews the query with (or without) its execution result."
    roles = [
        RoleRequirement("generator", "writes and revises SQL"),
        RoleRequirement("critic", "reviews the query", fallback="generator"),
    ]
    default_params = {"reflection_rounds": 1, "feedback": "execution"}  # feedback: execution | sql_only
    pass_criteria = ["final_correct"]

    def load_tasks(self) -> list[Task]:
        db = database()
        tasks = []
        for task_id, question, gold_sql in QUESTIONS:
            gold = run_query(db, gold_sql)
            if not gold.ok:
                raise RuntimeError(f"gold SQL for {task_id} is broken: {gold.error}")
            tasks.append(Task(id=task_id, prompt=question, data={"gold_sql": gold_sql, "gold_rows": gold.rows}))
        return tasks

    def fixtures(self) -> dict[str, Any]:
        with sqlite3.connect(database()) as db:
            dump = "\n".join(db.iterdump())
        return {"veloria_bikes.sql": dump + "\n", "schema.sql": schema_text() + "\n"}

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        db = database()
        generator, critic = models["generator"], models.get("critic", "generator")
        results: list[QueryResult] = []
        sqls: list[str] = []
        base = [
            system(
                "You write SQLite queries. Study the schema comments carefully. Return one query in a ```sql block."
            ),
        ]

        async def execute(sql: str) -> str:
            with ctx.trace.span("tool_call", "run_sql", input=sql) as span:
                result = run_query(db, sql)
                span.output = result.preview()
                span.attrs.update({"ok": result.ok, "error_kind": None if result.ok else "runtime"})
            sqls.append(sql)
            results.append(result)
            return sql

        async def draft() -> str:
            prompt = f"Schema:\n{schema_text()}\n\nQuestion: {task.prompt}"
            return await execute(extract_sql((await generator.complete([*base, user(prompt)])).content))

        async def critique(sql: str, _round: int) -> Critique:
            evidence = (
                f"\n\nExecution result:\n{results[-1].preview()}" if ctx.params["feedback"] == "execution" else ""
            )
            return await llm_critique(
                critic,
                [
                    system(
                        "You review SQL written by a colleague. Check it answers the question exactly, respects the "
                        "schema's units and sign conventions, and filters the right rows. Say 'accept' only if it is "
                        "correct as written."
                    ),
                    user(f"Schema:\n{schema_text()}\n\nQuestion: {task.prompt}\n\nSQL:\n{sql}{evidence}"),
                ],
            )

        async def revise(sql: str, review: Critique, _round: int) -> str:
            prompt = (
                f"Schema:\n{schema_text()}\n\nQuestion: {task.prompt}\n\nPrevious SQL:\n{sql}\n\n"
                f"Result:\n{results[-1].preview()}\n\nReviewer feedback:\n- "
                + "\n- ".join(review.issues or [review.summary])
            )
            return await execute(
                extract_sql(
                    (await generator.complete([*base, user(prompt + "\n\nWrite the corrected query.")])).content
                )
            )

        outcome = await reflect(
            draft=draft, critique=critique, revise=revise, rounds=ctx.params["reflection_rounds"], trace=ctx.trace
        )
        final_result = results[-1]
        return TrialOutput(
            final=outcome.final,
            env_state={"final_rows": final_result.rows, "final_error": final_result.error},
            extras={
                "sqls": sqls,
                "rows": [r.rows for r in results],
                "errors": [r.error for r in results],
                "verdicts": [c.verdict for c in outcome.critiques],
            },
        )

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [FunctionEvaluator("sql_steps", _step_scores), FunctionEvaluator("sql_final", _final_scores)]


def _correct(ctx: EvalContext, index: int) -> bool:
    rows, errors = ctx.output.extras["rows"], ctx.output.extras["errors"]
    return errors[index] is None and result_columns_cover(ctx.task.data["gold_rows"], rows[index])


def _step_scores(ctx: EvalContext) -> list[Score]:
    first_ok = ctx.output.extras["errors"][0] is None
    first_correct = _correct(ctx, 0)
    scores = [
        Score(name="draft_executes", value=float(first_ok), level="step", passed=first_ok),
        Score(name="draft_correct", value=float(first_correct), level="step", passed=first_correct),
    ]
    verdicts = ctx.output.extras["verdicts"]
    if verdicts:
        flagged = verdicts[0] == "revise"
        # Reviewer confusion indicators; the report turns their means into precision/recall.
        scores += [
            Score(name="critic_tp", value=float(flagged and not first_correct), level="step"),
            Score(name="critic_fp", value=float(flagged and first_correct), level="step"),
            Score(name="critic_fn", value=float(not flagged and not first_correct), level="step"),
            Score(
                name="critic_verdict_correct",
                value=float(flagged != first_correct),
                level="step",
                passed=flagged != first_correct,
            ),
        ]
    return scores


def _final_scores(ctx: EvalContext) -> list[Score]:
    last = len(ctx.output.extras["rows"]) - 1
    final_correct = _correct(ctx, last)
    regressed = _correct(ctx, 0) and not final_correct
    return [
        Score(name="final_correct", value=float(final_correct), level="e2e", passed=final_correct),
        Score(name="regressed", value=float(regressed), level="e2e", passed=not regressed),
        Score(name="sql_attempts", value=float(last + 1), level="e2e"),
    ]
