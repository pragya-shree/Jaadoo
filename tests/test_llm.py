"""
Tests for LLM Abstraction, Retry Engine, Error Handling & Mock Providers.
"""

import sys
import os
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.llm.base import (
    LLMProvider,
    LLMResult,
    RateLimitError,
    ProviderUnavailableError,
    AuthError,
    with_retry
)
from backend.llm.gemini import GeminiProvider
from backend.llm.factory import get_provider, register_provider
from backend import agent
from backend import database as db
from backend.main import chat_endpoint, ChatRequest

# ==================== MOCK PROVIDER ====================

class MockProvider(LLMProvider):
    """Configurable mock LLM provider for deterministic testing."""

    def __init__(
        self,
        behavior: str = "success",
        fail_count_before_success: int = 0,
        suggested_delay: Optional[float] = None,
        sleep_log: Optional[List[float]] = None
    ):
        self.behavior = behavior
        self.fail_count_before_success = fail_count_before_success
        self.attempts = 0
        self.suggested_delay = suggested_delay
        self.sleep_log = sleep_log if sleep_log is not None else []

    def sleep_recorder(self, seconds: float):
        self.sleep_log.append(seconds)

    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> LLMResult:
        if self.behavior == "auth_error":
            raise AuthError("Simulated missing or invalid API key.")
        
        if self.behavior == "unavailable":
            raise ProviderUnavailableError("Simulated mothership link failure (503).")

        def _op():
            self.attempts += 1
            if self.behavior == "rate_limit_always":
                raise Exception("429 Resource Exhausted: Quota exceeded")
            
            if self.behavior == "rate_limit_then_success":
                if self.attempts <= self.fail_count_before_success:
                    raise Exception("429 Resource Exhausted: Please retry")
                
            return LLMResult(
                text='{"reply": "Greetings, terrestrial!", "reaction": "waving", "user_memory": {"key": "Pet", "value": "Cat named Luna"}, "earth_knowledge": {"topic": "Bicycles", "alien_understanding": "Two-wheeled pedal devices humans balance upon."}, "diary_entry": {"title": "Two Wheel Balancing", "category": "Behaviour", "observation": "Humans ride unstable metal frames without falling.", "confusion_level": 7}}'
            )

        def _is_rl(e: Exception) -> Tuple[bool, Optional[float]]:
            if "429" in str(e):
                return True, self.suggested_delay
            return False, None

        # Execute through the real with_retry utility
        return with_retry(
            operation=_op,
            is_rate_limit=_is_rl,
            max_retries=2,
            sleep_fn=self.sleep_recorder,
            max_total_delay=10.0
        )

# ==================== TEST CASES ====================

def test_with_retry_logic():
    print("Testing with_retry() engine...")
    sleep_calls: List[float] = []

    # 1. Success on first try
    res = with_retry(
        operation=lambda: "ok",
        is_rate_limit=lambda e: (False, None),
        max_retries=2,
        sleep_fn=sleep_calls.append
    )
    assert res == "ok"
    assert len(sleep_calls) == 0
    print("  [PASS] with_retry: immediate success without delay.")

    # 2. 429 then retry success
    attempts = [0]
    def op_retry():
        attempts[0] += 1
        if attempts[0] == 1:
            raise Exception("429 rate limit")
        return "success_on_retry"

    res = with_retry(
        operation=op_retry,
        is_rate_limit=lambda e: (True, 1.5),
        max_retries=2,
        sleep_fn=sleep_calls.append
    )
    assert res == "success_on_retry"
    assert len(sleep_calls) == 1
    assert sleep_calls[-1] == 1.5
    print("  [PASS] with_retry: 429 retried once and succeeded.")

    # 3. 429 exhausted (2 retries fail -> RateLimitError)
    exhaust_calls = 0
    def op_always_fail():
        nonlocal exhaust_calls
        exhaust_calls += 1
        raise Exception("429 quota")

    try:
        with_retry(
            operation=op_always_fail,
            is_rate_limit=lambda e: (True, 0.5),
            max_retries=2,
            sleep_fn=sleep_calls.append
        )
        assert False, "Should have raised RateLimitError!"
    except RateLimitError:
        assert exhaust_calls == 3  # 1 initial + 2 retries
        print("  [PASS] with_retry: 429 exhausted raises RateLimitError.")

    # 4. Cap honored retry delay at 10.0 seconds
    try:
        with_retry(
            operation=op_always_fail,
            is_rate_limit=lambda e: (True, 12.0),  # Single delay exceeds 10s cap
            max_retries=2,
            sleep_fn=sleep_calls.append,
            max_total_delay=10.0
        )
        assert False, "Should have raised RateLimitError when delay > 10s!"
    except RateLimitError as e:
        assert "exceeded 10.0s cap" in str(e)
        print("  [PASS] with_retry: delay capped at 10s raises RateLimitError.")

def test_factory_and_gemini_init():
    print("Testing factory and provider discovery...")
    
    # 1. Unknown provider raises clear ValueError
    try:
        get_provider("nonexistent_ai_engine")
        assert False, "Should have raised ValueError for unknown provider!"
    except ValueError as e:
        assert "Unknown LLM provider" in str(e)
        print("  [PASS] get_provider: unknown provider raises clear ValueError.")

    # 2. GeminiProvider with missing key raises AuthError when client accessed
    gemini = GeminiProvider(api_key="")
    try:
        gemini._get_client()
        assert False, "Should have raised AuthError for empty API key!"
    except AuthError:
        print("  [PASS] GeminiProvider: missing key raises AuthError.")

def test_agent_with_mock_provider():
    print("Testing Agent processing with MockProvider...")

    # 1. Success case -> source='ai', memories extracted
    mock_success = MockProvider(behavior="success")
    res = agent.process_user_message(
        message="I love bicycles",
        session_id="test_ai_session",
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Earthling",
        provider=mock_success
    )
    assert res["source"] == "ai"
    assert res["is_demo"] is False
    assert res["user_memory"] is not None
    assert res["earth_knowledge"] is not None
    assert res["diary_entry"] is not None
    print("  [PASS] Agent: success case returned source='ai' with full extraction.")

    # 2. 429 then retry success -> source='ai'
    mock_retry_success = MockProvider(behavior="rate_limit_then_success", fail_count_before_success=1)
    res = agent.process_user_message(
        message="Tell me more",
        session_id="test_ai_session",
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Earthling",
        provider=mock_retry_success
    )
    assert res["source"] == "ai"
    assert len(mock_retry_success.sleep_log) == 1
    print("  [PASS] Agent: 429 retried via shared retry logic and succeeded with source='ai'.")

    # 3. 429 exhausted -> friendly in-character message, source='fallback'
    mock_429 = MockProvider(behavior="rate_limit_always")
    res = agent.process_user_message(
        message="Hello",
        session_id="test_ai_session",
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Earthling",
        provider=mock_429
    )
    assert res["source"] == "fallback"
    assert res["is_demo"] is True
    assert "overheating" in res["reply"] or "antenna" in res["reply"]
    print(f"  [PASS] Agent: 429 exhausted returned in-character message ('{res['reply'][:45]}...').")

    # 4. Missing key / AuthError -> friendly in-character message, source='fallback'
    mock_auth = MockProvider(behavior="auth_error")
    res = agent.process_user_message(
        message="Hello",
        session_id="test_ai_session",
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Earthling",
        provider=mock_auth
    )
    assert res["source"] == "fallback"
    assert "authentication key" in res["reply"]
    print(f"  [PASS] Agent: AuthError returned clear config instruction ('{res['reply'][:45]}...').")

def test_fallback_protection_in_db():
    print("Testing Database protection: No knowledge/diary saved on fallback...")
    db.init_db()
    sess = "sess_fallback_guard_test"

    diary_before = len(db.get_all_diary_entries())
    knowledge_before = len(db.get_all_earth_knowledge())

    # Send message with fallback (no API key configured or simulated failure)
    res = chat_endpoint(ChatRequest(
        session_id=sess,
        message="Explain dark matter and aliens",
        user_name="Scientist"
    ))
    assert res["source"] == "fallback"

    diary_after = len(db.get_all_diary_entries())
    knowledge_after = len(db.get_all_earth_knowledge())

    assert diary_after == diary_before, "Alien diary MUST NOT be modified on fallback!"
    assert knowledge_after == knowledge_before, "Earth knowledge MUST NOT be modified on fallback!"
    print("  [PASS] DB Protection: Knowledge and Diary entries remained unchanged during fallback.")

    # Verify fallback message is not returned when exclude_fallback=True
    recent_for_llm = db.get_recent_messages(sess, limit=8, exclude_fallback=True)
    assert not any(m.get("source") == "fallback" for m in recent_for_llm)
    print("  [PASS] History Filtering: Fallback messages excluded from conversation history sent to LLM.")

if __name__ == "__main__":
    try:
        test_with_retry_logic()
        test_factory_and_gemini_init()
        test_agent_with_mock_provider()
        test_fallback_protection_in_db()
        print("\n>>> ALL LLM & REFACTORING TESTS PASSED (100%)! <<<")
    except Exception as e:
        print(f"\n[FAIL] Test encountered an error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

