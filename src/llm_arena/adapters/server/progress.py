"""Rich progress bar for the CLI, driven by run events."""

from __future__ import annotations

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from llm_arena.runner.events import BudgetExceeded, RunEvent, RunFinished, RunStarted, RunWarning, TrialFinished


class RichProgressSink:
    def __init__(self, console: Console, run_dir: str) -> None:
        self.console = console
        self.run_dir = run_dir
        self._progress = Progress(
            TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(), console=console
        )
        self._task: TaskID | None = None
        self._refused = 0  # trials the spend limit turned away (status "budget")

    def __call__(self, event: RunEvent) -> None:
        if isinstance(event, RunStarted):
            done = event.total - event.pending
            self.console.print(f"[bold]{event.run_id}[/]: {event.total} trials ({done} already done) → {self.run_dir}")
            self._progress.start()
            self._task = self._progress.add_task("trials", total=event.pending)
        elif isinstance(event, TrialFinished) and self._task is not None:
            self._progress.advance(self._task)
            self._refused += event.status == "budget"
        elif isinstance(event, BudgetExceeded):
            if event.limit_usd == 0:
                self.console.print("[yellow]a $0.00 spend limit runs free models only; paid calls are refused[/]")
            else:
                self.console.print(
                    f"[yellow]spend limit reached: ${event.spent_usd:.2f} of ${event.limit_usd:.2f}; "
                    "paid calls that don't fit are refused[/]"
                )
        elif isinstance(event, RunWarning):
            self.console.print(f"[yellow]warning: {event.message}[/]")
        elif isinstance(event, RunFinished):
            self._progress.stop()
            if event.spent_usd:
                self.console.print(f"model spend: ${event.spent_usd:.4f}")
            if self._refused:
                trials = "trial" if self._refused == 1 else "trials"
                self.console.print(f"[yellow]{self._refused} {trials} refused by the spend limit[/]")
