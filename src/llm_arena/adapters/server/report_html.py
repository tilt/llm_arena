"""Render a run summary into one self-contained HTML file (Plotly inlined by default, works offline)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from llm_arena.adapters.server.duckdb_store import DuckDBStore
from llm_arena.report.aggregate import RunSummary, summarize
from llm_arena.runner.ports import RunStore

_TEMPLATES = Path(__file__).parent / "templates"
MAX_TRACE_TRIALS = 400
MAX_SPAN_CHARS = 1500
PLOTLY_CDN = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"


def build_report(run_dir: Path, *, inline_plotly: bool = True) -> Path:
    store = DuckDBStore(run_dir)
    summary = summarize(store.load_run())
    environment = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    environment.filters["pct"] = lambda v: "–" if v is None or _nan(v) else f"{100 * v:.0f}%"
    environment.filters["num"] = lambda v, d=2: "–" if v is None or _nan(v) else f"{v:,.{d}f}"
    html = environment.get_template("report.html.j2").render(
        s=summary,
        chart_data=script_json(_chart_data(summary)),
        traces=_trace_views(store, summary),
        plotly_js=_plotly_js() if inline_plotly else None,
        plotly_cdn=PLOTLY_CDN,
        overall=_overall(summary),
        csp=_csp(inline_plotly),
    )
    target = run_dir / "report.html"
    target.write_text(html, encoding="utf-8")
    return target


# Characters that could end a <script> element or break JavaScript parsing inside it.
_SCRIPT_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "\u2028": "\\u2028", "\u2029": "\\u2029"}


def script_json(value: Any) -> str:
    """JSON that is safe to embed in an inline <script>: config or model names like '</script><img …>' stay data."""
    text = json.dumps(value, default=_json_default)
    for char, escaped in _SCRIPT_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


def _csp(inline_plotly: bool) -> str:
    """The report needs only its own inline script and styles (plus the pinned Plotly CDN when not inlined)."""
    scripts = "'unsafe-inline'" + ("" if inline_plotly else " https://cdn.jsdelivr.net")
    return (f"default-src 'none'; script-src {scripts}; style-src 'unsafe-inline'; img-src data: blob:; "
            "font-src data:; base-uri 'none'; form-action 'none'")  # fmt: skip


def _nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _json_default(value: Any) -> Any:
    return None if _nan(value) else str(value)


def _plotly_js() -> str:
    from plotly.offline import get_plotlyjs

    return str(get_plotlyjs())


def _overall(summary: RunSummary) -> dict[str, Any]:
    trials = summary.trials
    return {
        "trials": len(trials),
        "pass_rate": sum(bool(t["passed"]) for t in trials) / len(trials) if trials else float("nan"),
        "errors": sum(t["status"] != "ok" for t in trials),
        "cost": sum(t["cost_usd"] or 0.0 for t in trials),
        "judge_cost": sum(t["judge_cost_usd"] or 0.0 for t in trials),
        "tokens": sum((t["prompt_tokens"] or 0) + (t["completion_tokens"] or 0) for t in trials),
        "judge": summary.config_json.get("judge"),
    }


def _clean(value: float) -> float | None:
    return None if _nan(value) else value


def _chart_data(summary: RunSummary) -> dict[str, Any]:
    configs, scenarios = summary.config_names, summary.scenarios
    lookup = {(c.config, c.scenario): c for c in summary.configs}
    matrix = [
        [_clean(lookup[(cfg, sc)].pass_rate) if (cfg, sc) in lookup else None for sc in scenarios] for cfg in configs
    ]

    per_config_tokens: dict[str, list[float]] = {}
    per_config_pass: dict[str, list[float]] = {}
    for c in summary.configs:
        per_config_tokens.setdefault(c.config, []).append(c.mean_tokens)
        per_config_pass.setdefault(c.config, []).append(c.pass_rate)
    scatter = [
        {
            "config": name,
            "tokens": sum(per_config_tokens[name]) / len(per_config_tokens[name]),
            "pass_rate": sum(per_config_pass[name]) / len(per_config_pass[name]),
        }
        for name in configs
    ]

    per_scenario: dict[str, Any] = {}
    for scenario in scenarios:
        members = sorted((c for c in summary.configs if c.scenario == scenario), key=lambda c: c.pass_rate)
        step_metrics = sorted({m for c in members for m, v in c.step_means.items() if 0.0 <= v <= 1.0})
        per_scenario[scenario] = {
            "bars": [
                {
                    "config": c.config,
                    "rate": _clean(c.pass_rate),
                    "low": _clean(c.ci_low),
                    "high": _clean(c.ci_high),
                    "n": c.trials,
                }
                for c in members
            ],
            "step": {
                "configs": [c.config for c in members],
                "metrics": step_metrics,
                "values": [[_clean(c.step_means.get(m, float("nan"))) for m in step_metrics] for c in members],
            },
        }
    return {
        "heatmap": {"configs": configs, "scenarios": scenarios, "values": matrix},
        "scatter": scatter,
        "scenarios": per_scenario,
        "ratings": summary.ratings,
    }


def _trace_views(store: RunStore, summary: RunSummary) -> list[dict[str, Any]]:
    views = []
    for trial in summary.trials[:MAX_TRACE_TRIALS]:
        payload = store.load_trace(trial["trial_id"])
        spans = payload["spans"] if payload else []
        views.append(
            {
                **trial,
                "scores": sorted(
                    summary.scores.get(trial["trial_id"], []), key=lambda s: (s["level"] != "e2e", s["name"])
                ),
                "spans": [_span_view(span) for span in spans],
            }
        )
    return views


def _span_view(span: dict[str, Any]) -> dict[str, Any]:
    def clip(value: Any) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str, indent=1)
        return text if len(text) <= MAX_SPAN_CHARS else text[:MAX_SPAN_CHARS] + " …"

    shown_input = (
        span["input"][-2:] if span["kind"] == "llm_call" and isinstance(span["input"], list) else span["input"]
    )
    return {
        **{
            k: span.get(k)
            for k in ("kind", "name", "role", "model", "error", "duration_s", "prompt_tokens", "completion_tokens")
        },
        "input": clip(shown_input) if shown_input is not None else "",
        "output": clip(span["output"] or ""),
        "attrs": clip({k: v for k, v in span["attrs"].items() if v not in (None, [], {})}),
    }


def summary_as_json(summary: RunSummary) -> str:
    return json.dumps(
        {
            "configs": [asdict(c) for c in summary.configs],
            "paired_tests": [asdict(t) for t in summary.paired_tests],
            "ratings": summary.ratings,
            "decisions": [d.model_dump() for d in summary.decisions],
            "replacements": [asdict(e) for e in summary.replacements],
        },
        default=_json_default,
        indent=2,
    )
