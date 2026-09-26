"""`arena` command line: models, scenarios, runs, reports, judge calibration, mock services."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from llm_arena.adapters.server.clients import get_client
from llm_arena.adapters.server.discovery import discover
from llm_arena.core.errors import ArenaError
from llm_arena.llm.errors import LLMError
from llm_arena.llm.pricing import load_prices
from llm_arena.llm.probe import ProbeResult, probe_model
from llm_arena.llm.registry import PROVIDERS, load_model_specs, resolve_model
from llm_arena.llm.spec import ModelSpec

app = typer.Typer(help="Evaluate local and remote LLMs on benchmarks and agentic patterns.", no_args_is_help=True)
models_app = typer.Typer(help="Inspect configured and served models.", no_args_is_help=True)
app.add_typer(models_app, name="models")
console = Console()

ModelsFile = Annotated[Path, typer.Option("--models", help="Model specs YAML")]
DEFAULT_MODELS = Path("configs/models.yaml")
PRICES_FILE = Path("configs/prices.yaml")


@app.callback()
def _setup() -> None:
    load_dotenv()
    if PRICES_FILE.exists():
        load_prices(PRICES_FILE)


def _specs(path: Path) -> dict[str, ModelSpec]:
    return load_model_specs(path) if path.exists() else {}


@models_app.command("list")
def models_list(
    models_file: ModelsFile = DEFAULT_MODELS,
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable catalog (e.g. for a UI)")] = False,
    needs: Annotated[
        list[str] | None, typer.Option("--needs", help="Only models with this capability (tools, vision, reasoning)")
    ] = None,
    show_all: Annotated[bool, typer.Option("--all", help="Include dated OpenAI snapshots")] = False,
) -> None:
    """Discover installed/available models (Ollama, LM Studio, OpenAI) plus curated aliases from models.yaml."""
    catalog = asyncio.run(discover())
    entries = catalog.filter(needs=frozenset(needs or []), snapshots=show_all)
    if json_out:
        payload = {
            "models": [e.as_dict() for e in entries],
            "aliases": {k: v.model_dump() for k, v in _specs(models_file).items()},
            "unavailable": catalog.errors,
        }
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    table = Table(
        "ref (use in experiments)", "params", "quant", "ctx", "tools", "vision", "think", "loaded", "$ in/out per Mtok"
    )
    for e in entries:
        caps = e.spec.capabilities
        tools = "✓" if caps.tools else "json"
        price = (
            "free (local)"
            if e.source != "openai"
            else (
                f"{e.input_cost_per_mtok:g} / {e.output_cost_per_mtok:g}"
                if e.input_cost_per_mtok is not None
                else "unknown"
            )
        )
        table.add_row(
            e.ref,
            e.parameters or "",
            e.quantization or "",
            f"{e.context_length:,}" if e.context_length else "",
            tools,
            "✓" if caps.vision else "",
            "✓" if caps.reasoning else "",
            {True: "●", False: "", None: ""}[e.loaded],
            price,
        )
    console.print(table)
    for source, error in catalog.errors.items():
        console.print(f"[yellow]{source} unavailable:[/] {escape(error)}")
    aliases = _specs(models_file)
    if aliases:
        console.print(f"Curated aliases in {models_file}: {', '.join(sorted(aliases))}", style="dim")


@models_app.command("ping")
def models_ping(
    names: Annotated[
        list[str] | None, typer.Argument(help="Aliases or provider:model refs (default: all configured)")
    ] = None,
    models_file: ModelsFile = DEFAULT_MODELS,
) -> None:
    """Smoke-test chat, tool calling and structured output for each model."""
    specs = _specs(models_file)
    discovered = asyncio.run(discover()).specs()
    targets = [resolve_model(name, specs, discovered) for name in names] if names else list(specs.values())

    async def probe_all() -> list[ProbeResult]:
        return [
            await probe_model(spec, get_client(spec)) for spec in targets
        ]  # sequential: local servers load one model at a time

    def mark(ok: bool) -> str:
        return "[green]✓[/]" if ok else "[red]✗[/]"

    table = Table("model", "reachable", "chat", "tools", "structured", "first reply s", "errors")
    for r in asyncio.run(probe_all()):
        latency = f"{r.first_token_latency_s:.1f}" if r.first_token_latency_s else "–"
        table.add_row(
            r.name,
            mark(r.reachable),
            mark(r.chat_ok),
            mark(r.tools_ok),
            mark(r.structured_ok),
            latency,
            "; ".join(r.errors)[:120],
        )
    console.print(table)


@app.command()
def scenarios() -> None:
    """List available scenarios and benchmarks with their roles and parameters."""
    from llm_arena.scenarios.base import SCENARIOS, get_scenario

    get_scenario("email_assistant")  # triggers registration
    table = Table("name", "pattern", "roles", "params", "pass criteria")
    for name, cls in sorted(SCENARIOS.items()):
        roles = ", ".join(
            r.name + ("?" if r.fallback else "") + (f" [{','.join(r.needs)}]" if r.needs else "") for r in cls.roles
        )
        table.add_row(name, cls.pattern, escape(roles), json.dumps(cls.default_params), ", ".join(cls.pass_criteria))
    console.print(table)
    console.print(escape("role? = optional (falls back to another role); [vision] = capability required"), style="dim")


@app.command()
def run(
    config: Annotated[Path, typer.Argument(help="Experiment YAML")],
    run_id: Annotated[str | None, typer.Option(help="Resume or name a run (skips finished trials)")] = None,
    live: Annotated[bool, typer.Option(help="Allow live web/arXiv search backends")] = False,
    limit: Annotated[int | None, typer.Option(help="Override tasks per scenario")] = None,
    report: Annotated[bool, typer.Option(help="Build the HTML report afterwards")] = True,
    dry_run: Annotated[bool, typer.Option(help="Only show the trial plan")] = False,
    docker: Annotated[bool, typer.Option(help="Run model-written code in Docker (--network none)")] = False,
    runs_dir: Annotated[Path, typer.Option(help="Where runs are stored")] = Path("runs"),
) -> None:
    """Run an experiment: scenarios × model configs × tasks × repeats."""
    from llm_arena.adapters.server.duckdb_store import DuckDBStore
    from llm_arena.adapters.server.progress import RichProgressSink
    from llm_arena.adapters.server.runtime import server_runtime
    from llm_arena.runner.config import load_experiment
    from llm_arena.runner.run import ExperimentRunner, describe_plan, new_run_id

    try:
        experiment = load_experiment(config)
        if limit is not None:
            experiment = experiment.model_copy(update={"limit": limit})
        run_id = run_id or new_run_id(experiment.name)
        run_dir = runs_dir / run_id
        runner = ExperimentRunner(
            experiment, server_runtime(docker_sandbox=docker), run_id=run_id, live=live,
            model_specs=_specs(Path(experiment.models_file)), sink=RichProgressSink(console, str(run_dir)),
        )  # fmt: skip
        if dry_run:
            asyncio.run(runner.prepare())
            console.print(describe_plan(runner.plan()))
            return
        runner.store = DuckDBStore(run_dir)
        asyncio.run(runner.run())
    except (ArenaError, LLMError) as exc:
        console.print(f"[red]error:[/] {exc}")
        raise typer.Exit(1) from exc
    if report:
        _report(run_dir)


@app.command("report")
def report_cmd(
    run: Annotated[str, typer.Argument(help="Run id or path to a run directory")],
    runs_dir: Annotated[Path, typer.Option(help="Where runs are stored")] = Path("runs"),
    cdn: Annotated[bool, typer.Option(help="Load Plotly from a CDN instead of inlining it (smaller file)")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Also write summary.json")] = False,
) -> None:
    """Build the static HTML report for a run."""
    run_dir = Path(run) if Path(run).is_dir() else runs_dir / run
    _report(run_dir, inline=not cdn, json_out=json_out)


def _report(run_dir: Path, *, inline: bool = True, json_out: bool = False) -> None:
    from llm_arena.adapters.server.duckdb_store import DuckDBStore
    from llm_arena.adapters.server.report_html import build_report, summary_as_json
    from llm_arena.report.aggregate import summarize

    path = build_report(run_dir, inline_plotly=inline)
    summary = summarize(DuckDBStore(run_dir).load_run())
    if json_out:
        (run_dir / "summary.json").write_text(summary_as_json(summary), encoding="utf-8")
    console.print(f"report: [link=file://{path.resolve()}]{path}[/link]")
    table = Table("scenario", "config", "pass rate", "pass^k", "tokens/trial", "errors")
    for c in summary.configs:
        table.add_row(
            c.scenario, c.config, f"{c.pass_rate:.0%}", f"{c.pass_hat_k:.0%}", f"{c.mean_tokens:,.0f}", str(c.errors)
        )
    console.print(table)


@app.command("judge-calibrate")
def judge_calibrate(
    judge: Annotated[str, typer.Argument(help="Judge model alias or provider:model")],
    rubric: Annotated[str, typer.Argument(help="Rubric name, e.g. report_quality, writing_quality, brief_quality")],
    examples: Annotated[Path, typer.Argument(help="JSONL with task/response/label(pass|fail)")],
    models_file: ModelsFile = DEFAULT_MODELS,
) -> None:
    """Agreement and Cohen's kappa between a judge and human labels."""
    from llm_arena.eval.calibration import calibrate
    from llm_arena.scenarios.chart_codegen import CHART_RUBRIC
    from llm_arena.scenarios.launch_brief import BRIEF_RUBRIC
    from llm_arena.scenarios.reflection_writing import WRITING_RUBRIC
    from llm_arena.scenarios.research_report import REPORT_RUBRIC

    rubrics = {r.name: r for r in (REPORT_RUBRIC, WRITING_RUBRIC, BRIEF_RUBRIC, CHART_RUBRIC)}
    if rubric not in rubrics:
        raise typer.BadParameter(f"unknown rubric; choose from {sorted(rubrics)}")
    client = get_client(resolve_model(judge, _specs(models_file), asyncio.run(discover()).specs()))
    result = asyncio.run(calibrate(client, rubrics[rubric], examples))
    console.print(
        f"{result.judge} on {result.rubric}: n={result.n} agreement={result.agreement:.0%} kappa={result.kappa:.2f}"
    )
    console.print(result.confusion)
    if not result.trustworthy:
        console.print("[yellow]kappa below 0.6: treat this judge's scores as indicative only[/]")


@app.command("mock-email")
def mock_email(port: int = 8025) -> None:
    """Serve the seeded mock mailbox over HTTP (extra `server`) for demos and manual testing."""
    import uvicorn

    from llm_arena.adapters.server.email_http import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=port)


@app.command()
def ui(
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1")] = 8765,
    runs_dir: Annotated[Path, typer.Option(help="Where runs are stored")] = Path("runs"),
    static: Annotated[Path | None, typer.Option(help="Built web UI directory (default: web/dist or bundled)")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open the browser")] = True,
    models_file: ModelsFile = DEFAULT_MODELS,
) -> None:
    """Start the local app: web UI + API over the discovered local and remote models (127.0.0.1 only)."""
    import threading
    import webbrowser

    import uvicorn

    from llm_arena.adapters.server.duckdb_store import DuckDBStore
    from llm_arena.adapters.server.runtime import server_runtime
    from llm_arena.server.app import create_app
    from llm_arena.service import ArenaService

    service = ArenaService(
        server_runtime(), store_factory=lambda run_id: DuckDBStore(runs_dir / run_id), model_specs=_specs(models_file)
    )
    static_dir = static or next((d for d in (Path("web/dist"), _bundled_web()) if (d / "index.html").exists()), None)
    url = f"http://127.0.0.1:{port}"
    console.print(f"LLM Arena at [link={url}]{url}[/link]  (runs in {runs_dir}/, Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(service, runs_dir=runs_dir, static_dir=static_dir), host="127.0.0.1", port=port, log_level="warning"
    )


def _bundled_web() -> Path:
    return Path(__file__).parent / "server" / "web"


@app.command()
def contracts(
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("contracts"),
    check: Annotated[bool, typer.Option(help="Fail if the checked-in contracts are stale (CI)")] = False,
) -> None:
    """Export JSON Schemas, scenario data and conformance vectors for other runtimes and the web UI."""
    from llm_arena.adapters.server.subprocess_sandbox import SubprocessSandbox
    from llm_arena.contracts import export, stale_files

    if check:
        stale = asyncio.run(stale_files(out, SubprocessSandbox()))
        if stale:
            console.print(f"[red]{len(stale)} contract files are stale[/] — run `arena contracts`:")
            for path in stale[:20]:
                console.print(f"  {path}")
            raise typer.Exit(1)
        console.print("contracts are up to date")
        return
    written = asyncio.run(export(out, SubprocessSandbox()))
    console.print(f"wrote {len(written)} contract files to {out}/")


@app.command()
def providers() -> None:
    """Show provider defaults (base URLs are overridable via env vars)."""
    table = Table("provider", "base url", "base url env", "api key env", "concurrency")
    for name, d in PROVIDERS.items():
        table.add_row(
            name, d.base_url or "(sdk default)", d.base_url_env or "", d.api_key_env or "", str(d.concurrency)
        )
    console.print(table)


if __name__ == "__main__":
    app()
