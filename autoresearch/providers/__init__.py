from __future__ import annotations

from .base import LLMProvider, ProviderResponse, ToolCall
from .anthropic import AnthropicProvider
from .openai import OpenAIProvider
from .ollama import OllamaProvider

__all__ = [
    "LLMProvider",
    "ProviderResponse",
    "ToolCall",
    "AnthropicProvider",
    "OpenAIProvider",
    "OllamaProvider",
    "make_provider",
]


def make_provider(config: "Config") -> LLMProvider:  # type: ignore[name-defined]
    """Create an LLMProvider instance from a Config object.

    Routes based on config.provider:
    - "anthropic" → AnthropicProvider
    - "openai"    → OpenAIProvider
    - "ollama"    → OllamaProvider

    Args:
        config: A loaded Config instance.

    Returns:
        An LLMProvider ready to use.

    Raises:
        ValueError: If the provider name is not recognised.
    """
    from autoresearch.config import Config  # local import to avoid circular deps

    provider = config.provider
    model_name = config.model_name
    api_key = config.api_key or ""

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model_name)
    elif provider == "openai":
        return OpenAIProvider(api_key=api_key, model=model_name)
    elif provider == "ollama":
        return OllamaProvider(model=model_name)
    else:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            "Supported providers: 'anthropic', 'openai', 'ollama'."
        )
