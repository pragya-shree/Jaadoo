"""
Personality & Conversation-Quality Tests for JAADOO

Tests:
  1. Curiosity questions appear only on the configured interval (every CURIOSITY_INTERVAL turns).
  2. Curiosity is suppressed when the user looks annoyed / message is very short.
  3. Diary entries are skipped for trivial messages via the MockProvider.
  4. Banned catchphrases are NOT present as examples in JAADOO_SYSTEM_PROMPT.
  5. The curiosity_question field in a live (mock) AI reply is always Python-controlled,
     never whatever the LLM returned.
  6. Demo responses no longer contain the old banned phrases.
  7. reset_curiosity_state clears the counter properly.
"""

import sys
import os
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import agent
from backend.llm.base import LLMProvider, LLMResult, with_retry, RateLimitError
from backend.llm.factory import register_provider


# ---------------------------------------------------------------------------
# Minimal mock provider — always returns a valid JSON reply with no curiosity
# ---------------------------------------------------------------------------

class PersonalityMock(LLMProvider):
    """Returns configurable JSON replies for personality testing."""

    def __init__(self, diary_entry=None, curiosity_in_llm_output=None):
        import json
        payload = {
            "reply": "Hello, earth creature.",
            "reaction": "curious",
            "user_memory": None,
            "earth_knowledge": None,
            "diary_entry": diary_entry,
            "curiosity_question": curiosity_in_llm_output,  # LLM tries to inject one — Python must override
        }
        self._text = json.dumps(payload)

    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> LLMResult:
        return LLMResult(text=self._text)


class TrivialMock(LLMProvider):
    """Returns diary_entry = null always, to simulate LLM correctly skipping trivial entries."""

    def generate(self, messages: List[Dict[str, str]], system_prompt: str) -> LLMResult:
        import json
        return LLMResult(text=json.dumps({
            "reply": "Yes.",
            "reaction": "happy",
            "user_memory": None,
            "earth_knowledge": None,
            "diary_entry": None,
            "curiosity_question": None,
        }))


# ---------------------------------------------------------------------------
# Helper: drive N turns through process_user_message with a mock provider
# ---------------------------------------------------------------------------

def _send_turns(session_id: str, messages: List[str], mock: LLMProvider) -> List[dict]:
    results = []
    for msg in messages:
        r = agent.process_user_message(
            message=msg,
            session_id=session_id,
            recent_messages=[],
            user_memories=[],
            earth_knowledge=[],
            user_name="Tester",
            provider=mock,
        )
        results.append(r)
    return results


# ===========================================================================
# TEST 1: Curiosity fires on the configured interval
# ===========================================================================

def test_curiosity_interval():
    print("Testing Curiosity Mode — interval enforcement...")
    interval = agent.CURIOSITY_INTERVAL
    sess = "ptest_curiosity_interval"
    agent.reset_curiosity_state(sess)
    mock = PersonalityMock()

    messages = [f"message {i}" for i in range(1, interval * 2 + 1)]
    results = _send_turns(sess, messages, mock)

    questions_at = [i + 1 for i, r in enumerate(results) if r.get("curiosity_question")]
    expected_at = list(range(interval, interval * 2 + 1, interval))

    assert questions_at == expected_at, (
        f"Curiosity questions appeared at turns {questions_at}, expected {expected_at}"
    )
    print(f"  [PASS] Curiosity fires exactly at turns {expected_at} (interval={interval}).")


# ===========================================================================
# TEST 2: Curiosity is suppressed for very short or annoyed messages
# ===========================================================================

def test_curiosity_suppressed_on_frustration():
    print("Testing Curiosity Mode — suppression for short/annoyed messages...")
    interval = agent.CURIOSITY_INTERVAL
    sess = "ptest_curiosity_suppressed"
    agent.reset_curiosity_state(sess)
    mock = PersonalityMock()

    # Drive interval-1 neutral turns so the next turn would normally fire
    _send_turns(sess, [f"msg {i}" for i in range(interval - 1)], mock)

    # This is turn `interval` — but the message is a frustrated one-word reply
    r = agent.process_user_message(
        message="no",  # very short, matches frustration heuristic
        session_id=sess,
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Tester",
        provider=mock,
    )
    # Should be suppressed
    assert r.get("curiosity_question") is None, (
        f"Curiosity should have been suppressed for a very short/annoyed message, got: {r.get('curiosity_question')}"
    )
    print("  [PASS] Curiosity suppressed when user message is very short / frustrated.")


# ===========================================================================
# TEST 3: Python overrides any curiosity_question the LLM returns
# ===========================================================================

def test_python_overrides_llm_curiosity():
    print("Testing Curiosity Mode — Python overrides LLM-injected curiosity...")
    interval = agent.CURIOSITY_INTERVAL
    sess = "ptest_llm_override"
    agent.reset_curiosity_state(sess)

    # LLM tries to inject its own curiosity question
    mock = PersonalityMock(curiosity_in_llm_output="Why do humans blink?")

    # Non-interval turn — LLM injects a question but Python must suppress it
    r = agent.process_user_message(
        message="I love playing chess.",
        session_id=sess,
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Tester",
        provider=mock,
    )
    # Turn 1 is not an interval turn, so curiosity_question must be None
    assert r.get("curiosity_question") is None, (
        f"Python should suppress LLM curiosity on non-interval turns, got: {r.get('curiosity_question')}"
    )
    print("  [PASS] Python correctly overrides LLM-injected curiosity on non-interval turn.")

    # Now drive to an interval turn — Python should inject its OWN question, not the LLM's
    agent.reset_curiosity_state(sess)
    for i in range(interval - 1):
        agent.process_user_message(
            message=f"neutral message {i}",
            session_id=sess,
            recent_messages=[],
            user_memories=[],
            earth_knowledge=[],
            user_name="Tester",
            provider=mock,
        )
    r_interval = agent.process_user_message(
        message="I enjoy reading books.",
        session_id=sess,
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Tester",
        provider=mock,
    )
    q = r_interval.get("curiosity_question")
    assert q is not None, "Expected a curiosity question on interval turn."
    # The LLM mock injects "Why do humans blink?" — Python must pick from CURIOSITY_QUESTIONS instead
    assert q in agent.CURIOSITY_QUESTIONS, (
        f"Python should use CURIOSITY_QUESTIONS list, got: {q}"
    )
    assert q != "Why do humans blink?", (
        "Python must not pass through the LLM-generated curiosity question."
    )
    print("  [PASS] Python injects its own question from CURIOSITY_QUESTIONS on interval turn.")


# ===========================================================================
# TEST 4: Diary entries are null for trivial exchanges
# ===========================================================================

def test_diary_skipped_for_trivial_messages():
    print("Testing Alien Diary — skipped for trivial messages...")
    sess = "ptest_diary_trivial"
    agent.reset_curiosity_state(sess)
    mock = TrivialMock()

    trivial_messages = ["ok", "yes", "no", "hi", "cool", "lol", "k"]
    results = _send_turns(sess, trivial_messages, mock)

    diary_created = [r.get("diary_entry") for r in results if r.get("diary_entry") is not None]
    assert len(diary_created) == 0, (
        f"Diary entries should not be created for trivial messages, got: {diary_created}"
    )
    print(f"  [PASS] No diary entries created across {len(trivial_messages)} trivial messages.")


# ===========================================================================
# TEST 5: Banned catchphrases are NOT in JAADOO_SYSTEM_PROMPT as examples
# ===========================================================================

def test_banned_phrases_not_in_system_prompt():
    print("Testing System Prompt — banned catchphrases not used as examples Jaadoo should say...")
    prompt = agent.JAADOO_SYSTEM_PROMPT

    # Phrases that must NOT appear as model examples / metaphor dictionary entries.
    # They are allowed ONLY inside a "do not use" prohibition rule.
    # We detect misuse by checking they don't appear on a line that starts with
    # a bullet point (  * , - , or similar) or as a dict entry (key = "...").
    banned_as_examples = [
        "glowing black mirror slabs",        # old phone metaphor
        "entering 8-hour paralyzed recharge mode",  # old sleep metaphor
        "furry four-legged household overlords",    # old pets metaphor
        "two-organism torso squeezing",             # old hugs metaphor
        "tiny green paper sheets",                  # old money metaphor
    ]

    for line in prompt.splitlines():
        stripped = line.strip()
        is_example_line = stripped.startswith("*") or (
            stripped.startswith("-") and ":" in stripped and "not" not in stripped.lower()
        )
        for phrase in banned_as_examples:
            if phrase.lower() in line.lower() and is_example_line:
                raise AssertionError(
                    f"Banned phrase used as an example in the system prompt: '{phrase}'\n  Line: {stripped}"
                )

    # Also verify the old HUMOROUS METAPHORS dictionary header is gone
    assert "HUMOROUS METAPHORS" not in prompt, (
        "Old 'HUMOROUS METAPHORS' dictionary section must be removed from the system prompt."
    )
    # And the old OCCASIONALLY SARCASTIC personality trait is gone
    assert "OCCASIONALLY SARCASTIC" not in prompt, (
        "Old 'OCCASIONALLY SARCASTIC' label must be removed from the system prompt."
    )
    print("  [PASS] No banned phrases used as examples. Old metaphor dictionary removed.")


# ===========================================================================
# TEST 6: Demo responses no longer contain old stock phrases
# ===========================================================================

def test_demo_responses_updated():
    print("Testing Demo Responses — old stock phrases removed...")
    old_phrases = [
        "cellular resuscitation",
        "8-hour biological paralysis",
        "facial cooling fluid",
        "ocular nozzles",
        "glowing black mirror",
    ]

    # Collect all demo reply texts
    all_reply_text = " ".join(item["reply"] for item in agent.DEMO_RESPONSES)

    found = [p for p in old_phrases if p.lower() in all_reply_text.lower()]
    assert len(found) == 0, (
        f"Old stock phrases still in demo responses: {found}"
    )
    print(f"  [PASS] Demo responses are free of old stock phrases.")


# ===========================================================================
# TEST 7: reset_curiosity_state clears counter
# ===========================================================================

def test_reset_curiosity_state():
    print("Testing reset_curiosity_state...")
    interval = agent.CURIOSITY_INTERVAL
    sess = "ptest_reset"
    agent.reset_curiosity_state(sess)
    mock = PersonalityMock()

    # Drive to just before an interval turn
    _send_turns(sess, [f"msg {i}" for i in range(interval - 1)], mock)

    # Reset
    agent.reset_curiosity_state(sess)

    # Now send one message — turn counter restarts at 1, should NOT fire
    r = agent.process_user_message(
        message="hello after reset",
        session_id=sess,
        recent_messages=[],
        user_memories=[],
        earth_knowledge=[],
        user_name="Tester",
        provider=mock,
    )
    assert r.get("curiosity_question") is None, (
        f"After reset, turn 1 should not produce a curiosity question, got: {r.get('curiosity_question')}"
    )
    print("  [PASS] reset_curiosity_state correctly clears the turn counter.")


# ===========================================================================
# TEST 8: curiosity_question is always null in LLM instructions
# ===========================================================================

def test_system_prompt_instructs_null_curiosity():
    print("Testing System Prompt — instructs LLM to return null curiosity_question...")
    prompt = agent.JAADOO_SYSTEM_PROMPT
    assert "curiosity_question" in prompt, "curiosity_question must appear in the prompt schema."
    assert "null" in prompt.lower(), "Prompt must tell the LLM to return null for curiosity_question."
    # Check the instruction says to leave it null
    assert any(phrase in prompt for phrase in [
        "Always set to null",
        "managed externally by Python",
        "managed externally",
        "Leave null",
    ]), "Prompt must explicitly instruct the LLM to leave curiosity_question null."
    print("  [PASS] System prompt correctly instructs LLM to return null for curiosity_question.")


# ===========================================================================
# RUNNER
# ===========================================================================

if __name__ == "__main__":
    try:
        test_curiosity_interval()
        test_curiosity_suppressed_on_frustration()
        test_python_overrides_llm_curiosity()
        test_diary_skipped_for_trivial_messages()
        test_banned_phrases_not_in_system_prompt()
        test_demo_responses_updated()
        test_reset_curiosity_state()
        test_system_prompt_instructs_null_curiosity()
        print("\n>>> ALL PERSONALITY TESTS PASSED (100%)! <<<")
    except Exception as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)
