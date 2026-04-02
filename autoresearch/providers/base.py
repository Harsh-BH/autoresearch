from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ProviderResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "tool_use" | "end_turn"


class LLMProvider(ABC):
    @abstractmethod
    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> ProviderResponse:
        """Send a request to the LLM and return a structured response.

        Args:
            messages: Conversation history in OpenAI-style format.
            tools: List of tool definitions in OpenAI-style format.
            system: System prompt string.

        Returns:
            A ProviderResponse containing text, tool_calls, and stop_reason.
        """
        ...
