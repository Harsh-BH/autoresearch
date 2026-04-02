from __future__ import annotations

import json
from typing import Optional

import openai as openai_sdk

from .base import LLMProvider, ProviderResponse, ToolCall


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
    ) -> None:
        client_kwargs: dict = {"api_key": api_key}
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        self._client = openai_sdk.OpenAI(**client_kwargs)
        self._model = model

    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> ProviderResponse:
        # Prepend system message if provided
        all_messages: list[dict] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs: dict = {
            "model": self._model,
            "messages": all_messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        text: str | None = message.content
        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    input_data = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    input_data = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        input=input_data,
                    )
                )

        finish_reason = choice.finish_reason or "stop"
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason in ("stop", "length", "content_filter"):
            stop_reason = "end_turn"
        else:
            stop_reason = finish_reason

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
        )
