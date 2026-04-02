"""LLM agentic loop for autoresearch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Imported lazily to avoid hard dependency at module import time; actual types
# are referenced via TYPE_CHECKING guards in signatures where needed.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autoresearch.providers.base import LLMProvider
    from autoresearch.tools import MetricResult, ToolExecutor

MAX_TOOL_CALLS = 30

SYSTEM_PROMPT = """\
You are an autonomous research agent. Your job is to iteratively improve a software project.

You have access to tools: read_file, write_file, run_command, list_files, report_metric.

Each iteration you should:
1. Explore the project (read files, understand structure)
2. Make ONE focused improvement (edit source code, add/fix tests, optimize)
3. Run tests or benchmarks to measure the result
4. Call report_metric with the measured value and a clear description of what you changed

Rules:
- Make only ONE change per iteration (keep diffs small and focused)
- Always run the benchmark/test after your change to get a real measurement
- If a change breaks something, revert it before calling report_metric
- Be specific in descriptions: "Added LRU cache to get_user() → reduced latency"
- The metric name and higher_is_better should be consistent across iterations\
"""


@dataclass
class AgentResult:
    """Result from a single agent iteration."""

    metric: "MetricResult | None"  # None if agent didn't call report_metric
    messages: list[dict] = field(default_factory=list)  # full conversation
    tool_calls_made: int = 0
    error: str | None = None


def _build_initial_message(task: str, project_root: str) -> str:
    """Construct the first user message for the agent."""
    root = Path(project_root)
    lines = [
        f"Project root: {root}",
        "",
        "## Task",
        task.strip(),
        "",
        "Start by exploring the project structure, then make one focused improvement,",
        "run benchmarks/tests to measure the result, and call report_metric.",
    ]
    return "\n".join(lines)


def _convert_messages_for_provider(
    messages: list[dict],
    provider_name: str,
) -> list[dict]:
    """Convert internal message format to provider-specific format.

    Internal format:
        {"role": "user", "content": "..."}
        {"role": "assistant", "content": "...", "tool_calls": [...]}
        {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}

    Anthropic expects tool results as "user" messages with content blocks:
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": ...}]}

    Anthropic also expects assistant tool calls encoded as content blocks:
        {"role": "assistant", "content": [{"type": "text", ...}, {"type": "tool_use", ...}]}

    OpenAI accepts the internal format natively (role "tool" with tool_call_id).
    """
    if provider_name not in ("anthropic",):
        # OpenAI / Ollama: use messages as-is (they accept role "tool")
        return messages

    # Anthropic conversion
    converted: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")

        if role == "assistant":
            content_blocks: list[dict] = []
            text = msg.get("content")
            if text:
                content_blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls", []):
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["input"],
                    }
                )
            converted.append({"role": "assistant", "content": content_blocks or (text or "")})

        elif role == "tool":
            # Collect consecutive tool results into a single user message
            tool_results: list[dict] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tr = messages[i]
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["tool_call_id"],
                        "content": tr["content"],
                    }
                )
                i += 1
            converted.append({"role": "user", "content": tool_results})
            continue  # i already advanced inside the while loop

        else:
            # "user" or other roles — pass through
            converted.append(msg)

        i += 1

    return converted


class Agent:
    """Orchestrates the LLM tool-call loop for one research iteration."""

    def __init__(
        self,
        provider: "LLMProvider",
        tool_executor: "ToolExecutor",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._system_prompt = system_prompt

    def run(
        self,
        task: str,
        project_root: str,
        history: list[dict],
    ) -> AgentResult:
        """Run one research iteration.

        Args:
            task: The task description (contents of program.md).
            project_root: Absolute path to the project being improved.
            history: Prior conversation messages (may be empty on first iteration).

        Returns:
            AgentResult with metric, messages, tool_calls_made, and optional error.
        """
        from autoresearch.tools import TOOLS  # lazy import

        # Reset last_metric at the start of each run
        self._tool_executor.last_metric = None

        # Build the initial user message for this iteration
        initial_content = _build_initial_message(task, project_root)
        messages: list[dict] = list(history) + [
            {"role": "user", "content": initial_content}
        ]

        tool_calls_made = 0

        # Detect provider type for message conversion
        provider_class_name = type(self._provider).__name__.lower()
        if "anthropic" in provider_class_name:
            provider_name = "anthropic"
        else:
            provider_name = "openai"

        while tool_calls_made < MAX_TOOL_CALLS:
            # Convert messages to provider format before sending
            api_messages = _convert_messages_for_provider(messages, provider_name)

            try:
                response = self._provider.call(
                    messages=api_messages,
                    tools=TOOLS,
                    system=self._system_prompt,
                )
            except Exception as exc:
                return AgentResult(
                    metric=None,
                    messages=messages,
                    tool_calls_made=tool_calls_made,
                    error=f"LLM call failed: {exc}",
                )

            # Append the assistant response to our internal message list
            assistant_msg: dict = {"role": "assistant", "content": response.text or ""}
            if response.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in response.tool_calls
                ]
            messages.append(assistant_msg)

            # If no tool calls, the agent is done
            if not response.tool_calls or response.stop_reason == "end_turn":
                break

            # Execute each tool call and collect results
            for tc in response.tool_calls:
                tool_calls_made += 1
                result_content = self._tool_executor.execute(tc.name, tc.input)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": result_content,
                    }
                )

            # Stop if report_metric was called
            if self._tool_executor.last_metric is not None:
                break

        else:
            # Exceeded MAX_TOOL_CALLS
            return AgentResult(
                metric=None,
                messages=messages,
                tool_calls_made=tool_calls_made,
                error=(
                    f"Safety limit reached: agent made {MAX_TOOL_CALLS} tool calls "
                    "without calling report_metric."
                ),
            )

        return AgentResult(
            metric=self._tool_executor.last_metric,
            messages=messages,
            tool_calls_made=tool_calls_made,
            error=None,
        )
