"""
Factory for instantiating the active LLM provider.
"""

import os
from typing import Optional, Dict, Type
from backend.llm.base import LLMProvider
from backend.llm.gemini import GeminiProvider

_PROVIDER_REGISTRY: Dict[str, Type[LLMProvider]] = {
    "gemini": GeminiProvider
}

def register_provider(name: str, provider_cls: Type[LLMProvider]):
    """Registers a provider implementation (useful for testing or extensions)."""
    _PROVIDER_REGISTRY[name.lower()] = provider_cls

def get_provider(
    provider_name: Optional[str] = None,
    **kwargs
) -> LLMProvider:
    """
    Returns an instance of the configured LLMProvider.
    Reads LLM_PROVIDER from environment if provider_name is omitted (default: 'gemini').
    Raises ValueError on unknown provider.
    """
    name = (provider_name or os.environ.get("LLM_PROVIDER", "gemini")).strip().lower()
    
    if name not in _PROVIDER_REGISTRY:
        supported = ", ".join(sorted(_PROVIDER_REGISTRY.keys()))
        raise ValueError(
            f"Unknown LLM provider '{name}'. Supported providers: [{supported}]. "
            "Please check LLM_PROVIDER in your .env file."
        )
    
    provider_cls = _PROVIDER_REGISTRY[name]
    return provider_cls(**kwargs)

