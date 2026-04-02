"""Tool definitions and executor for the autoresearch agent."""

from __future__ import annotations

import glob
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MetricResult:
    metric_name: str
    value: float
    higher_is_better: bool
    description: str


# Tool definitions in OpenAI/Anthropic tool format
TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file from the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read, relative to project root.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file in the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write, relative to project root.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the project root and return stdout, stderr, and exit code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 60).",
                    "default": 60,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the project matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Base directory to search in, relative to project root (default: '.').",
                    "default": ".",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (default: '**/*').",
                    "default": "**/*",
                },
            },
            "required": [],
        },
    },
    {
        "name": "report_metric",
        "description": (
            "Signal the end of the experiment and report the metric value. "
            "Call this once you have run your benchmark/test and have a result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric, e.g. 'test_pass_rate' or 'api_latency_ms'.",
                },
                "value": {
                    "type": "number",
                    "description": "Numeric value of the metric.",
                },
                "higher_is_better": {
                    "type": "boolean",
                    "description": "True if higher values are better (e.g. accuracy), False if lower is better (e.g. latency).",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what change was made this iteration.",
                },
            },
            "required": ["metric_name", "value", "higher_is_better", "description"],
        },
    },
]


class ToolExecutor:
    """Executes tool calls on behalf of the LLM agent."""

    def __init__(self, project_root: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.last_metric: MetricResult | None = None

    def _resolve_path(self, path: str) -> Path | None:
        """Resolve a relative path against project_root.

        Returns None if the resolved path escapes project_root (path traversal
        attack prevention).
        """
        resolved = (self.project_root / path).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError:
            return None
        return resolved

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Dispatch a tool call and return a string result.

        Never raises; on error returns an error string so the agent can
        self-correct.
        """
        handlers = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "run_command": self._run_command,
            "list_files": self._list_files,
            "report_metric": self._report_metric,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return f"Error: Unknown tool '{tool_name}'. Available tools: {', '.join(handlers)}."

        try:
            return handler(tool_input)
        except Exception as exc:  # pragma: no cover — safety net
            return f"Error: Unexpected exception in tool '{tool_name}': {exc}"

    # ------------------------------------------------------------------
    # Individual tool handlers
    # ------------------------------------------------------------------

    def _read_file(self, tool_input: dict[str, Any]) -> str:
        path_str = tool_input.get("path", "")
        if not path_str:
            return "Error: 'path' is required for read_file."

        resolved = self._resolve_path(path_str)
        if resolved is None:
            return f"Error: Path '{path_str}' traverses outside the project root. Access denied."

        if not resolved.exists():
            return f"Error: File '{path_str}' does not exist."

        if not resolved.is_file():
            return f"Error: '{path_str}' is a directory, not a file."

        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error: Could not read '{path_str}': {exc}"

    def _write_file(self, tool_input: dict[str, Any]) -> str:
        path_str = tool_input.get("path", "")
        content = tool_input.get("content")

        if not path_str:
            return "Error: 'path' is required for write_file."
        if content is None:
            return "Error: 'content' is required for write_file."

        resolved = self._resolve_path(path_str)
        if resolved is None:
            return f"Error: Path '{path_str}' traverses outside the project root. Access denied."

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return f"File '{path_str}' written successfully ({len(content)} bytes)."
        except OSError as exc:
            return f"Error: Could not write '{path_str}': {exc}"

    def _run_command(self, tool_input: dict[str, Any]) -> str:
        command = tool_input.get("command", "")
        timeout = tool_input.get("timeout", 60)

        if not command:
            return "Error: 'command' is required for run_command."

        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.project_root),
            )
            output = {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }
            return json.dumps(output)
        except subprocess.TimeoutExpired:
            output = {
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds.",
                "exit_code": -1,
            }
            return json.dumps(output)
        except OSError as exc:
            output = {
                "stdout": "",
                "stderr": f"Failed to run command: {exc}",
                "exit_code": -1,
            }
            return json.dumps(output)

    def _list_files(self, tool_input: dict[str, Any]) -> str:
        base_path_str = tool_input.get("path", ".")
        pattern = tool_input.get("pattern", "**/*")

        resolved_base = self._resolve_path(base_path_str)
        if resolved_base is None:
            return f"Error: Path '{base_path_str}' traverses outside the project root. Access denied."

        if not resolved_base.exists():
            return f"Error: Directory '{base_path_str}' does not exist."

        if not resolved_base.is_dir():
            return f"Error: '{base_path_str}' is not a directory."

        try:
            matches = sorted(resolved_base.glob(pattern))
            # Return paths relative to project root
            relative_paths = []
            for match in matches:
                if match.is_file():
                    try:
                        relative_paths.append(str(match.relative_to(self.project_root)))
                    except ValueError:
                        # Should not happen given resolve checks, but be safe
                        pass
            return json.dumps(relative_paths)
        except Exception as exc:
            return f"Error: Failed to list files: {exc}"

    def _report_metric(self, tool_input: dict[str, Any]) -> str:
        metric_name = tool_input.get("metric_name", "")
        value = tool_input.get("value")
        higher_is_better = tool_input.get("higher_is_better")
        description = tool_input.get("description", "")

        if not metric_name:
            return "Error: 'metric_name' is required for report_metric."
        if value is None:
            return "Error: 'value' is required for report_metric."
        if higher_is_better is None:
            return "Error: 'higher_is_better' is required for report_metric."

        try:
            value = float(value)
        except (TypeError, ValueError):
            return f"Error: 'value' must be a number, got {value!r}."

        self.last_metric = MetricResult(
            metric_name=metric_name,
            value=value,
            higher_is_better=bool(higher_is_better),
            description=description,
        )
        return "Metric reported."
