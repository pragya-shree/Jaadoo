"""
Base abstractions, exceptions, and retry utilities for LLM providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar
import time

T = TypeVar("T")

class RateLimitError(Exception):
    """Raised when the LLM provider returns a 429 or rate limit is exhausted."""
    pass

class ProviderUnavailableError(Exception):
    """Raised on connection, 5xx, or network errors communicating with LLM."""
    pass

class AuthError(Exception):
    """Raised when authentication fails or API key is missing/invalid."""
    pass

@dataclass
class LLMResult:
    text: str
    raw_response: Any = None

def with_retry(
    operation: Callable[[], T],
    is_rate_limit: Callable[[Exception], Tuple[bool, Optional[float]]],
    max_retries: int = 2,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_total_delay: float = 10.0
) -> T:
    """
    Executes operation with retry logic for 429 rate limits.
    - Retries up to max_retries times.
    - Honors retry delay from exception if available, else exponential backoff.
    - Caps total accumulated delay at max_total_delay seconds; raises RateLimitError if exceeded.
    - sleep_fn is injectable for testing without real delays.
    """
    total_delayed = 0.0
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except Exception as exc:
            is_rl, suggested_delay = is_rate_limit(exc)
            if not is_rl:
                raise
            
            if attempt >= max_retries:
                raise RateLimitError(f"Rate limit exceeded after {max_retries} retries: {exc}") from exc
            
            delay = suggested_delay if suggested_delay is not None else float(1.0 * (2 ** attempt))
            if total_delayed + delay > max_total_delay:
                raise RateLimitError(
                    f"Rate limit retry delay ({total_delayed + delay:.1f}s) exceeded {max_total_delay}s cap: {exc}"
                ) from exc
            
            total_delayed += delay
            sleep_fn(delay)
            
    # Fallback, should not be reached
    raise RateLimitError("Rate limit retries exhausted.")

class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> LLMResult:
        """
        Generates a completion from the provider.
        messages: List of dicts with 'role' ('user' or 'assistant') and 'content'.
        system_prompt: System-level instruction/persona.
        """
        pass

