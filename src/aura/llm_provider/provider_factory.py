"""Factory for instantiating the configured AURA LLM Provider."""

from __future__ import annotations

from aura.config import get_config
from aura.llm_provider.azure_openai_provider import AzureOpenAIProvider
from aura.llm_provider.base import BaseLLMProvider
from aura.llm_provider.bedrock_provider import BedrockLLMProvider
from aura.llm_provider.kong_provider import KongAIProvider
from aura.llm_provider.mock_provider import MockLLMProvider


def get_llm_provider(provider_override: str | None = None) -> BaseLLMProvider:
    """Return the configured LLM provider instance (defaults to MockLLMProvider)."""
    cfg = get_config()
    selected = (provider_override or cfg.llm_provider or "mock").lower().strip()
    if selected == "kong":
        return KongAIProvider()
    if selected == "bedrock":
        return BedrockLLMProvider()
    if selected in ("azure", "azure_openai"):
        return AzureOpenAIProvider()
    return MockLLMProvider()
