"""Typer CLI for autoresearch."""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="autoresearch",
    help="Autonomous research loop: let an LLM iteratively improve your project.",
    add_completion=False,
)

console = Console()
error_console = Console(stderr=True)

# Path to the bundled templates directory (sibling of this file)
_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------

@app.command()
def init() -> None:
    """Initialise a new autoresearch project in the current directory.

    Drops autoresearch.yaml and program.md into the current working directory.
    Edit program.md to describe your task, then run `autoresearch run`.
    """
    cwd = Path.cwd()
    config_dest = cwd / "autoresearch.yaml"
    program_dest = cwd / "program.md"

    config_src = _TEMPLATES_DIR / "autoresearch.yaml"
    program_src = _TEMPLATES_DIR / "program.md"

    # --- autoresearch.yaml ---
    if config_dest.exists():
        console.print(
            f"[yellow]Warning:[/yellow] [bold]{config_dest}[/bold] already exists."
        )
        overwrite = typer.confirm("Overwrite it?", default=False)
        if not overwrite:
            console.print("[dim]Skipping autoresearch.yaml.[/dim]")
        else:
            shutil.copy2(config_src, config_dest)
            console.print(f"[green]Wrote[/green] {config_dest}")
    else:
        shutil.copy2(config_src, config_dest)
        console.print(f"[green]Wrote[/green] {config_dest}")

    # --- program.md ---
    if program_dest.exists():
        console.print(
            f"[dim]program.md already exists — leaving it untouched.[/dim]"
        )
    else:
        shutil.copy2(program_src, program_dest)
        console.print(f"[green]Wrote[/green] {program_dest}")

    console.print()
    console.print(
        "[bold cyan]Next steps:[/bold cyan]\n"
        "  1. Edit [bold]program.md[/bold] to describe your task and metric.\n"
        "  2. Edit [bold]autoresearch.yaml[/bold] to set your model and API key.\n"
        "  3. Run [bold green]autoresearch run[/bold green] to start the loop."
    )


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

@app.command()
def run(
    iterations: Optional[int] = typer.Option(
        None,
        "--iterations",
        "-n",
        help="Override max_iterations from config.",
    ),
    time_limit: Optional[str] = typer.Option(
        None,
        "--time-limit",
        "-t",
        help="Override time_limit from config (e.g. '30m', '2h').",
    ),
    config: Path = typer.Option(
        Path("autoresearch.yaml"),
        "--config",
        "-c",
        help="Path to autoresearch.yaml config file.",
        exists=False,   # we give a nicer error ourselves
    ),
) -> None:
    """Run the autoresearch experiment loop with a live TUI dashboard."""
    # Lazy imports so the CLI stays fast even if heavy deps are missing
    try:
        from autoresearch.config import Config
    except ImportError as exc:
        error_console.print(f"[red]Import error:[/red] {exc}")
        raise typer.Exit(code=1)

    # Load and validate config
    try:
        cfg = Config.load(config)
    except FileNotFoundError as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        error_console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(code=1)

    # Apply CLI overrides
    if iterations is not None:
        cfg = cfg.model_copy(update={"max_iterations": iterations})
    if time_limit is not None:
        cfg = cfg.model_copy(update={"time_limit": time_limit})

    # Read task description from program.md
    program_path = Path.cwd() / "program.md"
    if program_path.exists():
        task = program_path.read_text(encoding="utf-8").strip()
    else:
        task = "(no program.md found)"
        console.print(
            "[yellow]Warning:[/yellow] program.md not found. "
            "Run [bold]autoresearch init[/bold] to create one."
        )

    # Build TUI
    try:
        from autoresearch.tui import Dashboard
    except ImportError as exc:
        error_console.print(f"[red]Import error (tui):[/red] {exc}")
        raise typer.Exit(code=1)

    tui = Dashboard(task=task, max_iterations=cfg.max_iterations)

    # Run the loop
    try:
        from autoresearch.loop import run_loop  # type: ignore[import]
    except ImportError:
        error_console.print(
            "[red]Error:[/red] autoresearch.loop is not available yet. "
            "Make sure the full package is installed."
        )
        raise typer.Exit(code=1)

    console.print(
        f"[bold green]Starting autoresearch[/bold green]  "
        f"model=[cyan]{cfg.model}[/cyan]  "
        f"max_iterations=[yellow]{cfg.max_iterations}[/yellow]  "
        f"time_limit=[yellow]{cfg.time_limit}[/yellow]"
    )

    tui.start()
    try:
        run_loop(cfg, tui)
    except KeyboardInterrupt:
        tui.stop()
        console.print()
        console.print("[yellow]Interrupted by user.[/yellow]")
        _print_summary()
        raise typer.Exit(code=0)
    except Exception as exc:
        tui.stop()
        error_console.print(f"[red]Run failed:[/red] {exc}")
        raise typer.Exit(code=1)
    else:
        tui.stop()
        console.print()
        console.print("[bold green]Run complete.[/bold green]")
        _print_summary()


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

@app.command()
def status() -> None:
    """Show a summary of experiment results from results.tsv."""
    results_path = Path.cwd() / "results.tsv"

    if not results_path.exists():
        console.print("[dim]No experiments run yet.[/dim]")
        console.print(
            "Run [bold green]autoresearch run[/bold green] to start the loop."
        )
        return

    rows = _read_results_tsv(results_path)
    if not rows:
        console.print("[dim]results.tsv is empty.[/dim]")
        return

    _print_results_table(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_results_tsv(path: Path) -> list[dict]:
    """Read results.tsv into a list of row dicts."""
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def _find_best_row(rows: list[dict]) -> dict | None:
    """Return the best kept row, or None if no kept rows exist."""
    kept = [r for r in rows if r.get("status", "").strip().lower() == "keep"]
    if not kept:
        return None

    # Determine direction from the first row that has the field
    higher_is_better = False
    for r in rows:
        hib = r.get("higher_is_better", "").strip().lower()
        if hib in ("true", "1", "yes"):
            higher_is_better = True
            break
        elif hib in ("false", "0", "no"):
            higher_is_better = False
            break

    try:
        if higher_is_better:
            return max(kept, key=lambda r: float(r.get("value", 0)))
        else:
            return min(kept, key=lambda r: float(r.get("value", 0)))
    except (ValueError, TypeError):
        return kept[-1]


def _print_results_table(rows: list[dict]) -> None:
    """Render results as a rich table."""
    best = _find_best_row(rows)
    best_iter = best.get("iteration") if best else None

    table = Table(
        title="[bold]Experiment Results[/bold]",
        show_header=True,
        header_style="bold magenta",
        box=None,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Iter", style="dim", width=6)
    table.add_column("Commit", width=9)
    table.add_column("Metric", width=18)
    table.add_column("Value", width=12)
    table.add_column("Status", width=10)
    table.add_column("Description")

    for row in rows:
        iteration = row.get("iteration", "?")
        commit = row.get("commit", "")[:7]
        metric_name = row.get("metric_name", "")
        value = row.get("value", "")
        raw_status = row.get("status", "").strip().lower()
        description = row.get("description", "")

        is_best = str(iteration) == str(best_iter)

        if raw_status == "keep":
            status_text = Text("✓ keep", style="bold green")
        else:
            status_text = Text("✗ discard", style="red")

        if is_best:
            iter_str = f"{iteration} ★"
            row_style = "bold bright_green"
        else:
            iter_str = str(iteration)
            row_style = "white" if raw_status == "keep" else "dim"

        table.add_row(
            iter_str,
            commit,
            metric_name,
            value,
            status_text,
            description,
            style=row_style,
        )

    console.print(table)

    if best:
        console.print(
            f"\n[bold]Best result:[/bold] iteration [yellow]{best_iter}[/yellow]  "
            f"value=[bright_green]{best.get('value', '?')}[/bright_green]  "
            f"[dim]{best.get('description', '')}[/dim]"
        )


def _print_summary() -> None:
    """Print a brief summary from results.tsv if it exists."""
    results_path = Path.cwd() / "results.tsv"
    if not results_path.exists():
        return
    rows = _read_results_tsv(results_path)
    if not rows:
        return
    best = _find_best_row(rows)
    total = len(rows)
    kept = sum(1 for r in rows if r.get("status", "").strip().lower() == "keep")
    console.print(
        f"[dim]Summary:[/dim] {total} iterations, "
        f"{kept} kept"
        + (
            f", best value=[bright_green]{best.get('value', '?')}[/bright_green] "
            f"at iteration [yellow]{best.get('iteration', '?')}[/yellow]"
            if best
            else ""
        )
    )
