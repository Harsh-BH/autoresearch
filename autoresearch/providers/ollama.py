from __future__ import annotations

from .openai import OpenAIProvider

_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_API_KEY = "ollama"


class OllamaProvider(OpenAIProvider):
    """Thin wrapper around OpenAIProvider for Ollama's OpenAI-compatible API."""

    def __init__(
        self,
        model: str,
        api_key: str = _DEFAULT_API_KEY,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=base_url)
