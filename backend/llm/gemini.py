"""
Google Gemini provider implementation using google-genai SDK.
This is the only file in the project that imports or interacts with the Gemini SDK.
"""

import os
import re
import logging
from typing import Callable, Dict, List, Optional, Tuple, Any
import time

from backend.llm.base import (
    LLMProvider,
    LLMResult,
    RateLimitError,
    ProviderUnavailableError,
    AuthError,
    with_retry
)

logger = logging.getLogger("jaadoo.llm.gemini")

def _is_rate_limit(exc: Exception) -> Tuple[bool, Optional[float]]:
    """Detects 429 / ResourceExhausted errors and extracts retry delay if present."""
    err_str = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    
    if (
        code == 429
        or "429" in err_str
        or "resource_exhausted" in err_str
        or "rate limit" in err_str
        or "quota exceeded" in err_str
    ):
        # Check for suggested retry delay in exception message (e.g. "retry in 4.5s")
        match = re.search(r"retry\s*(?:in|after)\s*([0-9.]+)\s*s?", err_str)
        delay = float(match.group(1)) if match else None
        return True, delay
    return False, None

def _is_auth_error(exc: Exception) -> bool:
    """Detects 401/403/invalid key errors."""
    err_str = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return (
        code in (401, 403)
        or "api_key" in err_str
        or "unauthenticated" in err_str
        or "permission_denied" in err_str
        or "invalid api key" in err_str
    )

class GeminiProvider(LLMProvider):
    """Gemini LLM Provider implementation."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        sleep_fn: Callable[[float], None] = time.sleep
    ):
        self.api_key = api_key if api_key is not None else (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.sleep_fn = sleep_fn
        self._client: Optional[Any] = None

    def _get_client(self):
        if not self.api_key or not self.api_key.strip():
            raise AuthError("GEMINI_API_KEY is not set or empty.")
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key.strip())
            except Exception as e:
                logger.error("Failed to initialize Google GenAI Client: %s", e)
                raise ProviderUnavailableError(f"Failed to initialize Gemini client: {e}") from e
        return self._client

    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> LLMResult:
        """Generates content via Gemini with exponential backoff for 429 rate limits."""
        client = self._get_client()
        from google.genai import types

        # Build prompt from messages
        prompt_parts = []
        for msg in messages:
            role = "Human" if msg["role"] == "user" else "Jaadoo"
            prompt_parts.append(f"{role}: {msg['content']}")
        full_prompt = "\n".join(prompt_parts) + "\nJaadoo (respond strictly as a JSON object matching the required schema):"

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.9,
            max_output_tokens=512,
            response_mime_type="application/json"
        )

        def _call_api():
            try:
                return client.models.generate_content(
                    model=self.model,
                    contents=full_prompt,
                    config=config
                )
            except Exception as e:
                # Log technical details server-side only
                logger.warning("Gemini API call failed: %s", e)
                if _is_auth_error(e):
                    raise AuthError(f"Gemini authentication failed: {e}") from e
                # Check for rate limit
                is_rl, _ = _is_rate_limit(e)
                if not is_rl:
                    # 5xx, network, connection, or generic failure
                    raise ProviderUnavailableError(f"Gemini service unavailable: {e}") from e
                # Rate limit exception is re-raised to be handled by with_retry
                raise

        response = with_retry(
            operation=_call_api,
            is_rate_limit=_is_rate_limit,
            max_retries=2,
            sleep_fn=self.sleep_fn,
            max_total_delay=10.0
        )

        raw_text = (response.text or "").strip()
        return LLMResult(text=raw_text, raw_response=response)

