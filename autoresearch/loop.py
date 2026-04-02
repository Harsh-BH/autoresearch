"""Main experiment loop for autoresearch."""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autoresearch.config import Config
    from autoresearch.tui import Dashboard

RESULTS_TSV_HEADER = [
    "iteration",
    "commit",
    "metric_name",
    "value",
    "higher_is_better",
    "status",
    "description",
]


def _load_task(project_root: Path) -> str:
    """Load the task description from program.md."""
    program_path = project_root / "program.md"
    if not program_path.exists():
        raise FileNotFoundError(
            f"program.md not found in {project_root}.\n"
            "Run 'autoresearch init' to create a template, or create program.md manually."
        )
    return program_path.read_text(encoding="utf-8")


def _ensure_results_tsv(results_path: Path) -> None:
    """Create results.tsv with header if it does not exist."""
    if not results_path.exists():
        with results_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(RESULTS_TSV_HEADER)


def _append_result(
    results_path: Path,
    iteration: int,
    commit: str,
    metric_name: str,
    value: float | str,
    higher_is_better: bool | str,
    status: str,
    description: str,
) -> None:
    """Append one row to results.tsv."""
    with results_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            [
                iteration,
                commit,
                metric_name,
                value,
                higher_is_better,
                status,
                description,
            ]
        )


def _is_better(
    new_value: float,
    best_value: float,
    higher_is_better: bool,
) -> bool:
    if higher_is_better:
        return new_value > best_value
    return new_value < best_value


def run_loop(config: "Config", tui: "Dashboard") -> None:
    """Run the autoresearch experiment loop.

    Args:
        config: Loaded configuration object.
        tui: Dashboard instance for live progress display.
    """
    from autoresearch.agent import Agent, SYSTEM_PROMPT
    from autoresearch.git_ops import GitOps
    from autoresearch.providers import make_provider
    from autoresearch.tools import ToolExecutor

    project_root = Path.cwd()
    results_path = project_root / "results.tsv"

    # Load task description
    task = _load_task(project_root)

    # Initialize collaborators
    git_ops = GitOps(str(project_root))
    tool_executor = ToolExecutor(str(project_root))
    provider = make_provider(config)
    agent = Agent(
        provider=provider,
        tool_executor=tool_executor,
        system_prompt=SYSTEM_PROMPT,
    )

    # Record baseline HEAD sha
    baseline_sha = git_ops.get_head_sha()

    # Initialize results.tsv
    _ensure_results_tsv(results_path)

    # Start TUI
    tui.start()

    max_iter = config.max_iterations
    time_limit = config.time_limit_seconds  # seconds; 0 means unlimited
    start_time = time.monotonic()

    best_metric = None
    best_iteration = None
    conversation_history: list[dict] = []

    try:
        for i in range(1, (max_iter if max_iter > 0 else 10 ** 9) + 1):
            # Check time limit
            elapsed = time.monotonic() - start_time
            if time_limit > 0 and elapsed >= time_limit:
                tui.log(f"Time limit of {config.time_limit} reached after {i - 1} iterations.")
                break

            # Reset last_metric before each run
            tool_executor.last_metric = None

            # Record pre-run state
            pre_sha = git_ops.get_head_sha()

            # Update TUI
            tui.update_status(iteration=i, max_iterations=max_iter, status="running...")

            # Run agent
            result = agent.run(
                task=task,
                project_root=str(project_root),
                history=conversation_history,
            )

            # Handle errors or missing metric
            if result.error or result.metric is None:
                error_msg = result.error or "Agent did not call report_metric."
                tui.log(f"Iter {i}: error — {error_msg}")
                git_ops.reset_hard(pre_sha)
                _append_result(
                    results_path,
                    iteration=i,
                    commit="",
                    metric_name="",
                    value="",
                    higher_is_better="",
                    status="error",
                    description=error_msg,
                )
                # Don't accumulate errored conversation into history
                continue

            metric = result.metric
            is_first = best_metric is None

            # Determine keep/discard
            if is_first or _is_better(metric.value, best_metric.value, metric.higher_is_better):
                commit_sha = git_ops.commit(
                    f"iter {i}: {metric.description} ({metric.metric_name}={metric.value})"
                )
                status = "keep"
                best_metric = metric
                best_iteration = i
            else:
                git_ops.reset_hard(pre_sha)
                commit_sha = pre_sha
                status = "discard"

            # Append to results.tsv
            _append_result(
                results_path,
                iteration=i,
                commit=commit_sha[:7] if commit_sha else "",
                metric_name=metric.metric_name,
                value=metric.value,
                higher_is_better=metric.higher_is_better,
                status=status,
                description=metric.description,
            )

            # Update TUI with iteration record
            tui.add_iteration(
                iteration=i,
                metric_name=metric.metric_name,
                value=metric.value,
                higher_is_better=metric.higher_is_better,
                status=status,
                description=metric.description,
                best_value=best_metric.value if best_metric else None,
                best_iteration=best_iteration,
            )

            # Accumulate conversation history for next iteration
            conversation_history = result.messages

            # Re-check time limit after iteration completes
            elapsed = time.monotonic() - start_time
            if time_limit > 0 and elapsed >= time_limit:
                tui.log(f"Time limit of {config.time_limit} reached after {i} iterations.")
                break

    finally:
        tui.stop()

    # Final summary
    if best_metric is not None:
        direction = "higher" if best_metric.higher_is_better else "lower"
        print(
            f"\nAutoresearch complete.\n"
            f"  Best result: {best_metric.metric_name} = {best_metric.value} "
            f"({direction} is better) at iteration {best_iteration}\n"
            f"  Description: {best_metric.description}\n"
            f"  Results written to: {results_path}\n"
        )
    else:
        print(
            "\nAutoresearch complete. No successful iterations recorded.\n"
            f"  Results written to: {results_path}\n"
        )
