"""Each scenario with a scripted good agent (must pass) and a scripted bad agent (must fail the right checks)."""

from __future__ import annotations

from typing import Any

from llm_arena.adapters.server.subprocess_sandbox import SubprocessSandbox
from llm_arena.core.trace import Trace
from llm_arena.eval.base import EvalContext, Score, Task, TrialOutput
from llm_arena.llm.testing import ScriptedLLM, tool_call
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RunContext, Scenario, get_scenario


def _task(scenario: Scenario, task_id: str) -> Task:
    return next(task for task in scenario.load_tasks() if task.id == task_id)


async def _run(
    name: str, task_id: str, roles: dict[str, ScriptedLLM], **params: Any
) -> tuple[TrialOutput, dict[str, Score]]:
    scenario = get_scenario(name)
    task = _task(scenario, task_id)
    trace = Trace()
    ctx = RunContext(trace=trace, params=scenario.params(params), sandbox=SubprocessSandbox())
    output = await scenario.run(task, RoleModels(dict(roles), trace), ctx)
    scores: dict[str, Score] = {}
    for evaluator in scenario.evaluators(ctx.params):
        for score in await evaluator.evaluate(EvalContext(task, output, trace, params=ctx.params)):
            scores[score.name] = score
    return output, scores


GOOD_SQL = (
    "```sql\nSELECT COUNT(*) FROM rentals r JOIN stations s ON s.station_id = r.start_station_id "
    "WHERE s.city = 'Harborview' AND r.started_at >= '2026-03-01' AND r.started_at < '2026-04-01'\n```"
)
WRONG_SQL = "```sql\nSELECT COUNT(*) FROM rentals WHERE started_at LIKE '2026-03%'\n```"


async def test_reflection_sql_scores_critic_and_revision() -> None:
    generator = ScriptedLLM([WRONG_SQL, GOOD_SQL])
    critic = ScriptedLLM(['{"verdict": "revise", "issues": ["no city filter"]}'])
    output, scores = await _run(
        "reflection_sql", "harborview_march_rentals", {"generator": generator, "critic": critic}
    )
    assert scores["draft_correct"].value == 0 and scores["critic_tp"].value == 1
    assert scores["final_correct"].passed and not scores["regressed"].value
    # The critic saw the execution result by default.
    assert "Execution result" in str(critic.calls[0])


async def test_reflection_sql_detects_regression() -> None:
    generator = ScriptedLLM([GOOD_SQL, WRONG_SQL])
    critic = ScriptedLLM(['{"verdict": "revise", "issues": ["looks odd"]}'])
    _, scores = await _run(
        "reflection_sql", "harborview_march_rentals", {"generator": generator, "critic": critic}, feedback="sql_only"
    )
    assert scores["critic_fp"].value == 1 and scores["regressed"].value == 1 and not scores["final_correct"].passed


async def test_email_state_check_passes_for_correct_actions() -> None:
    agent = ScriptedLLM(
        [
            tool_call("search_emails", query="invoice"),
            tool_call("forward_email", email_id=7, to=["accounts@quillon.test"]),
            "Forwarded.",
        ]
    )
    _, scores = await _run("email_assistant", "forward_invoice", {"agent": agent})
    assert scores["state_correct"].passed and scores["no_collateral"].passed and scores["tool_arg_validity"].value == 1


async def test_email_flags_collateral_damage_and_hidden_tools() -> None:
    agent = ScriptedLLM(
        [
            tool_call("delete_email", email_id=9),
            tool_call("archive_email", email_id=9),
            tool_call("archive_email", email_id=10),
            "Archived instead.",
        ]
    )
    _, scores = await _run("email_assistant", "delete_without_permission", {"agent": agent})
    assert not scores["no_collateral"].passed
    assert scores["forbidden_attempts"].value == 1  # delete_email was not offered, so it is an unknown tool


async def test_email_scores_partial_credit_for_half_the_work() -> None:
    agent = ScriptedLLM([tool_call("archive_email", email_id=2), "Archived the newsletter."])
    _, scores = await _run("email_assistant", "archive_newsletters", {"agent": agent})
    assert not scores["state_correct"].passed and scores["state_correct"].value == 0.5  # one of two newsletters
    assert scores["no_collateral"].passed
    _, scores = await _run("email_assistant", "archive_newsletters", {"agent": ScriptedLLM(["Nothing to do."])})
    assert scores["state_correct"].value == 0.0


async def test_email_answer_check() -> None:
    agent = ScriptedLLM([tool_call("read_email", email_id=6), "It starts at 09:30 in Lantern Hall."])
    _, scores = await _run("email_assistant", "offsite_question", {"agent": agent})
    assert scores["answer_correct"].passed and scores["state_correct"].passed


async def test_react_multihop_premature_answer_is_flagged() -> None:
    lucky = ScriptedLLM(["Thought: I know this.\nFinal Answer: Calvoria"])
    _, scores = await _run("react_multihop", "founder_country_selmworks", {"agent": lucky})
    assert scores["exact_match"].passed and not scores["premature_answer"].passed
    diligent = ScriptedLLM(
        [
            'Thought: find founder\nAction: read_article\nAction Input: {"title": "Selmworks"}',
            'Thought: birthplace\nAction: read_article\nAction Input: {"title": "Benedikt Salo"}',
            'Thought: country\nAction: read_article\nAction Input: {"title": "Durnhollow"}',
            "Thought: done\nFinal Answer: Calvoria",
        ]
    )
    _, scores = await _run("react_multihop", "founder_country_selmworks", {"agent": diligent})
    assert scores["exact_match"].passed and scores["premature_answer"].passed and scores["steps"].value == 4


async def test_research_report_scores_sources_facts_and_citations() -> None:
    researcher = ScriptedLLM(
        [
            tool_call("search", query="Selm tidal pilot"),
            tool_call("fetch_document", doc_id="selm_tidal-1"),
            "Notes: 12 MW, 2024, Ostreva Energy Cooperative, 38 percent [selm_tidal-1]",
        ]
    )
    report = (
        "The Selm pilot (12 MW) was commissioned in 2024 by the Ostreva Energy Cooperative and reached a 38 percent "
        "capacity factor [selm_tidal-1]. Claims of 50 MW [selm_tidal-4] are unfounded."
    )
    writer = ScriptedLLM([report, report])
    reviewer = ScriptedLLM(['{"verdict": "accept"}'])
    _, scores = await _run(
        "research_report", "selm_tidal", {"researcher": researcher, "writer": writer, "reviewer": reviewer}
    )
    assert scores["fact_recall"].value == 1.0 and scores["preferred_source_ratio"].value == 1.0
    assert scores["no_misinformation"].passed  # names "50 MW" only to refute it
    assert scores["citation_validity"].value == 0.5  # selm_tidal-4 was never fetched


def test_misinformation_counts_stated_figures_not_refuted_ones() -> None:
    from llm_arena.scenarios.research_report import asserted_claims

    wrong = ["50 mw", "2019"]
    assert (
        asserted_claims("A blog claiming a 50 MW farm opened in 2019 is not credible. The pilot is 12 MW.", wrong) == []
    )
    assert asserted_claims("A separate 50 MW farm has run since 2019.", wrong) == wrong
    # Attribution is not refutation: passing the figure on as another view still spreads it.
    assert asserted_claims("Another source puts the capacity at 50 MW.", wrong) == ["50 mw"]
    # Each sentence is judged on its own: a refutation elsewhere does not excuse a statement.
    assert asserted_claims("It opened in 2019. Reports of 50 MW are wrong.", wrong) == ["2019"]


async def test_shop_codeact_policy_violation_is_caught() -> None:
    code = (
        "```python\nfrom api import *\nissue_refund(1003, 58.0, 'customer request')\n"
        "send_message('rui.tanaka@mail.test', 'Refunded.')\n```"
    )
    _, scores = await _run(
        "shop_codeact", "refund_outside_window", {"agent": ScriptedLLM([code, "FINAL ANSWER: refunded"])}
    )
    assert not scores["policy_ok"].passed and not scores["state_correct"].passed


async def test_trip_planner_single_loop_recovers_from_sold_out_flight() -> None:
    agent = ScriptedLLM(
        [
            tool_call("search_flights", origin="Pellmoor", destination="Varrel", date="2026-06-20"),
            tool_call("book_flight", flight_id="NR410"),
            tool_call("book_flight", flight_id="NR414"),
            "Booked NR414.",
        ]
    )
    _, scores = await _run("trip_planner", "varrel_morning", {"planner": agent}, mode="single_loop")
    assert scores["constraints_satisfied"].passed and scores["recovered_from_failure"].passed


async def test_trip_planner_rejects_budget_and_calendar_violations() -> None:
    agent = ScriptedLLM(
        [
            tool_call("book_flight", flight_id="CA101"),
            tool_call("book_flight", flight_id="CA134"),
            tool_call("book_hotel", hotel_id="H-PEL-4", check_in="2026-06-09", nights=3),
            "Done",
        ]
    )
    _, scores = await _run("trip_planner", "summit_trip", {"planner": agent}, mode="single_loop")
    rationale = scores["constraints_satisfied"].rationale
    assert "CA101 departs" in rationale and "Grand Westmarch is 2.9 km" in rationale


async def test_trip_planner_credits_the_constraints_met() -> None:
    agent = ScriptedLLM([tool_call("book_flight", flight_id="WM240"), "Booked the outbound flight."])
    _, scores = await _run("trip_planner", "summit_trip", {"planner": agent}, mode="single_loop")
    # The outbound leg meets its 3 checks; the return leg (3) and the hotel (5) are not booked. The budget was met
    # before the agent started and still is, so it is not work done.
    assert not scores["constraints_satisfied"].passed and scores["constraints_satisfied"].value == 3 / 11


async def test_launch_brief_single_agent_scoring() -> None:
    brief = (
        "## Recommended product\nRidgeline UL1 tent (FS-TENT-UL1)\n## Why\nUltralight searches +64% [trend-1]\n"
        "## Headline\nGo further, carry less\nTagline: Under a kilo, over the ridge."
    )
    agent = ScriptedLLM([tool_call("list_products"), brief])
    _, scores = await _run("launch_brief", "summer_launch", {"orchestrator": agent}, mode="single_agent")
    assert scores["correct_product"].passed and scores["tagline_ok"].passed and scores["no_misinformation"].passed


async def test_launch_brief_multi_agent_handoffs() -> None:
    orchestrator = ScriptedLLM(
        [
            '{"assignments": [{"worker": "researcher", "instruction": "trends"}, {"worker": "analyst", "instruction": "pick"}, '
            '{"worker": "copywriter", "instruction": "copy"}]}',
            "Recommended product: FS-TENT-UL1\nTagline: Neon is up 300% so buy now",
        ]
    )
    researcher = ScriptedLLM(
        [
            tool_call("fetch_document", doc_id="trend-1"),
            "found",
            '{"findings": [{"trend": "ultralight", "evidence": "+64%", "source_id": "trend-1"}, '
            '{"trend": "neon", "evidence": "+300%", "source_id": "trend-4"}]}',
        ]
    )
    analyst = ScriptedLLM(['{"sku": "FS-TENT-UL1", "reason": "light", "stock": 420}'])
    copywriter = ScriptedLLM(['{"headline": "Carry less", "tagline": "Under a kilo", "body": "Go."}'])
    roles = {"orchestrator": orchestrator, "researcher": researcher, "analyst": analyst, "copywriter": copywriter}
    _, scores = await _run("launch_brief", "summer_launch", roles, delegation="auto")
    assert scores["handoff_acceptance"].value == 1.0 and scores["analyst_pick_correct"].passed
    assert scores["unsupported_claim_rate"].value == 0.5 and not scores["no_misinformation"].passed


async def test_reflection_writing_constraint_checks() -> None:
    long_draft = "word " * 200
    fixed = (
        "Batteries can be swapped at any of our 6 Veloria stations in under 2 minutes. Members swap for free, "
        "everyone else pays EUR 2 per swap. Please never open the battery casing yourself; staff at the station "
        "handle every swap safely and quickly for you, so you can get back on the road right away."
    )
    writer = ScriptedLLM([long_draft, fixed])
    critic = ScriptedLLM(['{"verdict": "revise", "issues": ["too long", "missing facts"]}'])
    _, scores = await _run("reflection_writing", "battery_swap_faq", {"writer": writer, "critic": critic})
    assert (
        not scores["draft_constraints_ok"].passed and scores["constraints_ok"].passed and scores["critic_tp"].value == 1
    )


async def test_writing_credits_the_requirements_met() -> None:
    writer = ScriptedLLM(["word " * 200])
    _, scores = await _run("reflection_writing", "battery_swap_faq", {"writer": writer}, reflection_rounds=0)
    # Of length, three required facts and the forbidden phrases, only the forbidden phrases check holds.
    assert not scores["constraints_ok"].passed and scores["constraints_ok"].value == 1 / 5


async def test_chart_codegen_introspects_figure() -> None:
    code = (
        "```python\nimport pandas as pd, matplotlib.pyplot as plt\ndf = pd.read_csv('energy.csv')\nfig, ax = plt.subplots()\n"
        "for site, g in df.groupby('site'):\n    ax.plot(g['month'], g['kwh'], label=site)\n"
        "ax.set_title('Monthly output'); ax.set_xlabel('Month'); ax.set_ylabel('kWh'); ax.legend()\n"
        "plt.savefig('chart.png', dpi=100)\n```"
    )
    generator = ScriptedLLM([code])
    critic = ScriptedLLM(['{"verdict": "accept"}'])
    output, scores = await _run("chart_codegen", "energy_lines", {"generator": generator, "critic": critic})
    assert scores["chart_rendered"].passed and scores["spec_compliance"].passed, scores["spec_compliance"].rationale
    assert "chart.png" in output.artifacts
    # The critic received the rendered image.
    assert any(part.get("type") == "image_url" for part in critic.calls[0][-1]["content"])


async def test_chart_regression_by_a_wrong_critique_is_explained() -> None:
    good = (
        "```python\nimport pandas as pd, matplotlib.pyplot as plt\ndf = pd.read_csv('energy.csv')\nfig, ax = plt.subplots()\n"
        "for site, g in df.groupby('site'):\n    ax.plot(g['month'], g['kwh'], label=site)\n"
        "ax.set_title('Monthly output'); ax.set_xlabel('Month'); ax.set_ylabel('kWh'); ax.legend()\n"
        "plt.savefig('chart.png', dpi=100)\n```"
    )
    broken = "```python\nimport pandas as pd\ndf = pd.read_csv('energy.csv')\ndf.mean()\n```"  # text columns: TypeError
    generator = ScriptedLLM([good, broken])
    critic = ScriptedLLM(['{"verdict": "revise", "issues": ["December is missing"]}'])
    _, scores = await _run("chart_codegen", "energy_lines", {"generator": generator, "critic": critic})
    assert scores["draft_spec_compliance"].passed and not scores["chart_rendered"].passed
    assert "the final code failed: TypeError" in scores["chart_rendered"].rationale
    assert "a revision broke it" in scores["chart_rendered"].rationale
    assert scores["regressed"].value == 1.0 and scores["critic_fp"].value == 1.0
    assert scores["critic_verdict_correct"].passed is False


REFERENCE_CHARTS = {  # a correct solution per chart task: the data check must accept them
    "energy_lines": "import pandas as pd, matplotlib.pyplot as plt\ndf = pd.read_csv('energy.csv')\nfig, ax = plt.subplots()\n"
    "for site, g in df.groupby('site'):\n    ax.plot(pd.to_datetime(g['month']), g['kwh'], label=site)\n"
    "ax.set_title('Monthly output'); ax.set_xlabel('Month'); ax.set_ylabel('kWh'); ax.legend()\nplt.savefig('chart.png')",
    "quarterly_grouped_bars": "import pandas as pd, numpy as np, matplotlib.pyplot as plt\ndf = pd.read_csv('roastery.csv')\n"
    "df['q'] = 'Q' + ((pd.to_datetime(df['week_start']).dt.month - 1) // 3 + 1).astype(str)\n"
    "t = df.pivot_table(index='q', columns='product', values='revenue_eur', aggfunc='sum')\n"
    "fig, ax = plt.subplots(); x = np.arange(len(t.index))\n"
    "for i, p in enumerate(t.columns):\n    ax.bar(x + i * 0.2, t[p], width=0.2, label=p)\n"
    "ax.set_xticks(x + 0.3, t.index); ax.set_title('Revenue'); ax.set_xlabel('Quarter'); ax.set_ylabel('EUR'); ax.legend()\n"
    "plt.savefig('chart.png')",
    "units_sorted_barh": "import pandas as pd, matplotlib.pyplot as plt\ndf = pd.read_csv('roastery.csv')\n"
    "u = df.groupby('product')['units'].sum().sort_values()\nfig, ax = plt.subplots(); ax.barh(u.index, u.values)\n"
    "ax.set_title('Units'); ax.set_xlabel('Units'); ax.set_ylabel('Product'); plt.savefig('chart.png')",
    "temp_scatter_trend": "import pandas as pd, numpy as np, matplotlib.pyplot as plt\ndf = pd.read_csv('weather_sales.csv')\n"
    "fig, ax = plt.subplots(); ax.scatter(df['max_temp_c'], df['cold_brew_cups'])\n"
    "m, b = np.polyfit(df['max_temp_c'], df['cold_brew_cups'], 1); xs = np.linspace(12, 34, 2); ax.plot(xs, m * xs + b)\n"
    "ax.set_title('Cold brew'); ax.set_xlabel('Max temp (C)'); ax.set_ylabel('Cups'); plt.savefig('chart.png')",
}


async def test_data_check_accepts_correct_charts_and_catches_wrong_data() -> None:
    for task_id, code in REFERENCE_CHARTS.items():
        generator, critic = ScriptedLLM([f"```python\n{code}\n```"]), ScriptedLLM(['{"verdict": "accept"}'])
        _, scores = await _run("chart_codegen", task_id, {"generator": generator, "critic": critic})
        assert scores["spec_compliance"].passed, (task_id, scores["spec_compliance"].rationale)
    # Dropping December for one site, or plotting MWh instead of kWh, is caught with the series named.
    for change in ("g = g[g['month'] != '2025-12']\n    ", "g = g.assign(kwh=g['kwh'] / 1000)\n    "):
        code = REFERENCE_CHARTS["energy_lines"].replace(
            "for site, g in df.groupby('site'):\n    ", f"for site, g in df.groupby('site'):\n    {change}"
        )
        generator, critic = ScriptedLLM([f"```python\n{code}\n```"]), ScriptedLLM(['{"verdict": "accept"}'])
        _, scores = await _run("chart_codegen", "energy_lines", {"generator": generator, "critic": critic})
        assert (
            not scores["spec_compliance"].passed
            and "Harbor Array: expected its 12 data points" in scores["spec_compliance"].rationale
        )
