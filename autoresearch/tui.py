"""Live rich TUI dashboard for the autoresearch experiment loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text


# Unicode block characters for sparkline (lowest to highest density)
_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """Return a sparkline string using unicode block characters.

    Given a list of floats, each value is mapped proportionally to one of
    the 8 block characters (▁▂▃▄▅▆▇█).

    Args:
        values: List of numeric values to render.

    Returns:
        A string of unicode block characters, one per value.
    """
    if not values:
        return ""
    if len(values) == 1:
        return _SPARK_CHARS[4]

    lo = min(values)
    hi = max(values)
    span = hi - lo

    chars = []
    for v in values:
        if span == 0:
            idx = 4  # middle block when all values are equal
        else:
            # Normalise to [0, 1] then scale to index 0–7
            idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
            idx = max(0, min(len(_SPARK_CHARS) - 1, idx))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars)


@dataclass
class IterationRecord:
    """Record of a single experiment iteration."""

    iteration: int
    metric_value: float
    status: str          # "keep" or "discard"
    description: str
    commit_sha: str | None = None


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a human-readable string."""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m elapsed"
    elif minutes > 0:
        return f"{minutes}m {secs:02d}s elapsed"
    else:
        return f"{secs}s elapsed"


class Dashboard:
    """Live rich TUI dashboard.

    Displays the current experiment status, metric history, and recent
    iteration results in a polished terminal UI.

    Args:
        task: The task description (first line of program.md).
        max_iterations: Maximum number of iterations configured.
    """

    def __init__(self, task: str, max_iterations: int) -> None:
        self._task = task
        self._max_iterations = max_iterations
        self._console = Console()
        self._live: Optional[Live] = None

        # Current state, updated by `update()`
        self._iteration: int = 0
        self._current_status: str = "starting..."
        self._current_description: str = ""
        self._elapsed: float = 0.0
        self._metric_name: str = ""
        self._metric_higher_is_better: Optional[bool] = None
        self._current_value: Optional[float] = None
        self._best_value: Optional[float] = None
        self._best_iter: int = 0
        self._history: List[IterationRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the live display."""
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            screen=False,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the live display."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def update(
        self,
        iteration: int,
        metric_result,          # MetricResult-like object (duck typed)
        status: str,
        elapsed_seconds: float,
        history: List[IterationRecord],
    ) -> None:
        """Refresh the dashboard with new experiment data.

        Args:
            iteration: Current iteration number (1-based).
            metric_result: Object with attributes: name, value,
                higher_is_better, description. Pass None while waiting.
            status: Human-readable status string, e.g. "running...",
                "keep", "discard".
            elapsed_seconds: Seconds since the run started.
            history: Full list of IterationRecord objects so far.
        """
        self._iteration = iteration
        self._status = status
        self._elapsed = elapsed_seconds
        self._history = list(history)

        if metric_result is not None:
            # Support both metric_name (MetricResult) and name (duck-typed)
            self._metric_name = getattr(
                metric_result, "metric_name", getattr(metric_result, "name", "metric")
            )
            self._metric_higher_is_better = getattr(
                metric_result, "higher_is_better", None
            )
            self._current_value = getattr(metric_result, "value", None)
            self._current_description = getattr(metric_result, "description", "")
        else:
            self._current_description = status

        # Recompute best from history
        if self._history:
            kept = [r for r in self._history if r.status == "keep"]
            if kept:
                hib = self._metric_higher_is_better
                if hib:
                    best = max(kept, key=lambda r: r.metric_value)
                else:
                    best = min(kept, key=lambda r: r.metric_value)
                self._best_value = best.metric_value
                self._best_iter = best.iteration
            else:
                self._best_value = None
                self._best_iter = 0

        if self._live is not None:
            self._live.update(self._render())

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _render(self) -> Panel:
        """Build and return the full dashboard renderable."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="task", size=3),
            Layout(name="current", size=4),
            Layout(name="metric", size=5),
            Layout(name="history", size=8),
            Layout(name="footer", size=3),
        )

        layout["header"].update(self._render_header())
        layout["task"].update(self._render_task())
        layout["current"].update(self._render_current())
        layout["metric"].update(self._render_metric())
        layout["history"].update(self._render_history())
        layout["footer"].update(self._render_footer())

        return Panel(layout, border_style="bright_blue", padding=(0, 1))

    def _render_header(self) -> Panel:
        iter_str = (
            f"iter {self._iteration}/{self._max_iterations}"
            if self._iteration > 0
            else f"0/{self._max_iterations}"
        )
        elapsed_str = _format_elapsed(self._elapsed)
        header_text = Text()
        header_text.append(" autoresearch ", style="bold bright_cyan")
        header_text.append("── ", style="dim")
        header_text.append(iter_str, style="bold yellow")
        header_text.append(" ── ", style="dim")
        header_text.append(elapsed_str, style="green")
        return Panel(header_text, border_style="blue", padding=(0, 1))

    def _render_task(self) -> Panel:
        first_line = self._task.splitlines()[0] if self._task else "(no task)"
        task_text = Text()
        task_text.append("Task: ", style="bold")
        task_text.append(first_line, style="italic")
        return Panel(task_text, title="[bold]Program[/bold]", border_style="blue", padding=(0, 1))

    def _render_current(self) -> Panel:
        is_running = "running" in getattr(self, "_status", "").lower()
        content = Text()

        if self._current_description:
            content.append(f'"{self._current_description}"', style="italic white")
            content.append("\n")

        content.append("Status: ", style="bold")
        if is_running:
            spinner = Spinner("dots", text=Text(self._status or "running...", style="yellow"))
            # Rich spinner cannot be embedded in Text; show text only
            content.append(self._status or "running...", style="bold yellow")
        else:
            status_str = getattr(self, "_status", "")
            if "keep" in status_str.lower():
                content.append(status_str, style="bold green")
            elif "discard" in status_str.lower():
                content.append(status_str, style="bold red")
            else:
                content.append(status_str, style="bold white")

        return Panel(
            content,
            title="[bold]Current Experiment[/bold]",
            border_style="blue",
            padding=(0, 1),
        )

    def _render_metric(self) -> Panel:
        hib = self._metric_higher_is_better
        direction = "higher is better" if hib else "lower is better"
        metric_label = self._metric_name or "metric"
        title = f"[bold]Metric: {metric_label} ({direction})[/bold]"

        content = Text()

        # Current and best values
        cur_str = (
            f"{self._current_value:.4g}"
            if self._current_value is not None
            else "—"
        )
        best_str = (
            f"{self._best_value:.4g} (iter {self._best_iter})"
            if self._best_value is not None
            else "—"
        )

        content.append("Current: ", style="bold")
        content.append(cur_str, style="cyan")
        content.append("    Best: ", style="bold")
        content.append(best_str, style="bright_green")
        content.append("\n")

        # Sparkline from history
        if self._history:
            values = [r.metric_value for r in self._history]
            spark = sparkline(values)
            content.append("History: ", style="bold")
            content.append(spark, style="bright_yellow")

        return Panel(content, title=title, border_style="blue", padding=(0, 1))

    def _render_history(self) -> Panel:
        table = Table(
            show_header=True,
            header_style="bold magenta",
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("#", style="dim", width=5)
        table.add_column("Value", width=12)
        table.add_column("", width=3)   # ✓/✗
        table.add_column("Description", ratio=1)

        recent = self._history[-5:] if self._history else []
        # Show newest first
        for record in reversed(recent):
            is_best = (
                self._best_value is not None
                and record.metric_value == self._best_value
                and record.status == "keep"
            )
            status_icon = Text("✓", style="green") if record.status == "keep" else Text("✗", style="red")
            iter_str = f"#{record.iteration}"
            val_str = f"{record.metric_value:.4g}"
            desc = record.description[:60] + ("…" if len(record.description) > 60 else "")

            if is_best:
                iter_str = f"#{record.iteration} ★"
                row_style = "bold bright_green"
            else:
                row_style = "white" if record.status == "keep" else "dim"

            table.add_row(iter_str, val_str, status_icon, desc, style=row_style)

        return Panel(
            table,
            title="[bold]Last 5 Iterations[/bold]",
            border_style="blue",
            padding=(0, 1),
        )

    def _render_footer(self) -> Panel:
        footer = Text(justify="center")
        footer.append("[q] quit", style="dim")
        footer.append("  ·  ", style="dim")
        footer.append("[p] pause", style="dim")
        return Panel(footer, border_style="blue", padding=(0, 0))
