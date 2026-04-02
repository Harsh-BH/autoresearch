from __future__ import annotations

import json

import anthropic

from .base import LLMProvider, ProviderResponse, ToolCall


def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-style tool definitions to Anthropic format.

    OpenAI format:
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { ... }
            }
        }

    Anthropic format:
        {
            "name": "...",
            "description": "...",
            "input_schema": { ... }
        }
    """
    converted = []
    for tool in tools:
        if tool.get("type") == "function":
            fn = tool["function"]
            converted.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        else:
            # Already in Anthropic format or unknown — pass through
            converted.append(tool)
    return converted


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> ProviderResponse:
        anthropic_tools = _convert_tools_to_anthropic(tools)

        kwargs: dict = {
            "model": self._model,
            "max_tokens": 8096,
            "system": system,
            "messages": messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = self._client.messages.create(**kwargs)

        text: str | None = None
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input if isinstance(block.input, dict) else {},
                    )
                )

        stop_reason = "tool_use" if tool_calls else "end_turn"
        if response.stop_reason:
            stop_reason = response.stop_reason

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )
