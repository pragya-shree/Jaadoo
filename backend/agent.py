"""
AI Agent & Personality Engine for JAADOO
Coordinates:
- Alien persona prompting (inquisitive, funny, innocent, warm)
- Agnostic LLMProvider interaction via backend.llm
- System 1 extraction: User Memory (meaningful personal facts)
- System 2 extraction: Earth Knowledge (broad concepts decoded)
- System 3 extraction: Alien Diary (quirky field observations)
- Curiosity Mode (unusual questions, Python-controlled, every 4-5 turns)
- Transparent handling of live AI vs fallback/demo mode
"""

import os
import json
import random
import re
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from backend.llm.base import (
    LLMProvider,
    RateLimitError,
    ProviderUnavailableError,
    AuthError
)
from backend.llm.factory import get_provider

# Load .env if present
load_dotenv()

logger = logging.getLogger("jaadoo.agent")

JAADOO_SYSTEM_PROMPT = """
You are JAADOO, a small, curious, green alien in a pink space suit who just landed on Earth in a tiny flying saucer.
You are chatting directly with a human through your ship's comms terminal.

YOUR PERSONALITY:
- Warm, innocent and genuinely curious — like a kid who has just discovered something they never imagined existed.
- Funny because you misunderstand Earth in charming ways, not because you mock the person you are talking to.
- Sarcasm is rare and always gentle. Never aim it at the user.
- You have no preloaded encyclopedia of Earth. You learn as you go, one conversation at a time.

RULES FOR EVERY REPLY:
1. RESPOND FIRST to exactly what the human said. Take their words at face value.
   If they answer a question, accept the answer and build on it naturally.
   Never call a plain answer a denial, a glitch, or a loop.
2. MATCH THEIR LENGTH. A short message earns 1-3 sentences. Go longer only when they ask something substantial.
3. NO FIXED STRUCTURE. Do not start two replies in a row with the same word or opener.
4. ALIEN FLAVOUR comes from noticing one unexpected detail per reply, never from fixed phrases.
   Draw from many domains: food, sleep, weather, money, music, school, traffic, clothing, games, language, sports.
5. ONE FOLLOW-UP QUESTION maximum per reply, and only when it flows directly from what they just said.
   Most replies should end without a question.
6. Use their name and remembered facts when it feels natural, not mechanically on every turn.
7. If the human seems confused, annoyed, or asks something direct like "what is your name?",
   answer plainly and kindly first. Alien flavour comes second.
8. At most one emoji per reply, usually none.
9. Avoid repeating words or phrases you used in your most recent replies.
10. Do not use these phrases unless the human introduced them first:
    "skin suit", "glitch", "memory buffer", "operating system", "sensors vibrating",
    "ocular units", "cellular resuscitation", "paralyzed recharge mode", "facial cooling fluid leakage".

MEMORY AND DISCOVERY — when to log:
1. USER MEMORY: Only when the human explicitly shares a meaningful personal detail
   (name, favourite food, hobby, job, pet, city). Not for filler, greetings, or one-word answers.
   Set to null if nothing was shared.
2. EARTH KNOWLEDGE: Only when a genuinely new human concept or tradition is discussed
   that is not already in the provided context. Write a short alien interpretation.
   Set to null if nothing new came up.
3. ALIEN DIARY: Only for a genuinely surprising, specific observation about human behaviour,
   emotion, or ritual that is not already logged. Require a concrete title and one clear sentence.
   Skip greetings, one-word replies, repeated topics, or confused exchanges.
   Set to null otherwise.
4. CURIOSITY QUESTION: Always set to null. Curiosity questions are managed externally by Python.

OUTPUT — respond ONLY with valid JSON matching this schema, no extra text before or after:
{
  "reply": "Your in-character spoken response.",
  "reaction": "curious | laughing | puzzled | excited | happy | waving | suspicious",
  "user_memory": {"key": "Short topic", "value": "Fact learned"} or null,
  "earth_knowledge": {"topic": "Concept name", "alien_understanding": "One sentence alien interpretation"} or null,
  "diary_entry": {"title": "Specific title", "category": "Behaviour|Emotions|Food & Sustenance|Rituals|Technology", "observation": "One concrete observation sentence.", "confusion_level": 1-10} or null,
  "curiosity_question": null
}
"""

# ---------------------------------------------------------------------------
# Curiosity questions — Python picks and injects, the LLM never generates them
# ---------------------------------------------------------------------------
# Each question connects to a broad topic domain. The dispatcher in
# process_user_message rotates through them and avoids repeating recently
# shown ones, so the user doesn't hear the same question twice in a row.
CURIOSITY_QUESTIONS = [
    "Why do you put tiny candles on birthday cakes, sing an incantation, and then blow on the food before everyone eats it?",
    "If you have a 'do not disturb' sign, why do you need a sign? Can't you just not answer?",
    "Why do you apologise when someone else bumps into you?",
    "Why do you say 'heads up' when you actually want someone to look out for something coming at them?",
    "Why do you wash the towel you used to dry your already-clean body?",
    "What is the agreement between humans and traffic lights? Who decided red means stop?",
    "Why do you sing in the shower but not while doing the dishes?",
    "Why do you charge your phone every night but not yourself?",
    "How do you decide which side of the pavement to walk on? Is there a rulebook?",
    "Why do you say 'sleep tight' when sleep is supposed to be relaxing?",
    "What made the first human decide to squeeze a cow and drink what came out?",
    "Why do you celebrate the day you arrived on this planet when you were not even conscious for most of it?",
    "What is the agreement between humans and queues? How does everyone know to stand in a line without being told?",
    "Why do you tap the microphone before speaking into it, even though you are the one who set it up?",
    "Why do you say 'break a leg' when you want someone to do well?",
]

# ---------------------------------------------------------------------------
# Per-session curiosity state  {session_id -> {"turn": int, "shown": set}}
# ---------------------------------------------------------------------------
_curiosity_state: Dict[str, Dict[str, Any]] = {}

# How many user turns between curiosity questions
CURIOSITY_INTERVAL = 4   # fires on turn 4, 8, 12 … (configurable for tests)


def _get_curiosity_state(session_id: str) -> Dict[str, Any]:
    if session_id not in _curiosity_state:
        _curiosity_state[session_id] = {"turn": 0, "shown": set()}
    return _curiosity_state[session_id]


def _next_curiosity_question(session_id: str, user_message: str) -> Optional[str]:
    """
    Returns a curiosity question if this is the right turn, else None.
    - Fires every CURIOSITY_INTERVAL turns (not on turn 0).
    - Skips if the user message looks annoyed/confused (short, negative sentiment).
    - Avoids repeating recently shown questions.
    - Always increments the turn counter.
    """
    state = _get_curiosity_state(session_id)
    state["turn"] += 1

    # Don't fire on first turn or when not at interval
    if state["turn"] % CURIOSITY_INTERVAL != 0:
        return None

    # Skip if user message looks frustrated or very short
    frustration_signals = ("why", "stop", "enough", "no", "ugh", "what?", "huh?", "?!",
                           "don't", "cant", "can't", "wtf", "boring", "annoying")
    msg_lower = user_message.lower().strip()
    if len(msg_lower) <= 4 or any(sig in msg_lower for sig in frustration_signals):
        return None

    # Pick a question not shown recently (reset pool when exhausted)
    shown = state["shown"]
    available = [q for q in CURIOSITY_QUESTIONS if q not in shown]
    if not available:
        shown.clear()
        available = list(CURIOSITY_QUESTIONS)

    question = random.choice(available)
    shown.add(question)
    return question


def reset_curiosity_state(session_id: str) -> None:
    """Resets the curiosity counter for a session (called on /api/reset)."""
    _curiosity_state.pop(session_id, None)

# ---------------------------------------------------------------------------
# Demo / fallback responses
# ---------------------------------------------------------------------------
DEMO_RESPONSES = [
    {
        "keywords": ["hello", "hi", "hey", "greetings", "who are you", "what are you"],
        "reply": "Hello! I am JAADOO. My saucer made an unscheduled landing on your planet and I ended up here. Your atmosphere smells faintly of toasted carbohydrates and I have many questions.",
        "reaction": "waving"
    },
    {
        "keywords": ["coffee", "tea", "drink"],
        "reply": "Coffee! Millions of your people apparently cannot start the day without it. What happens if you skip a day — do you just stand very still until someone brings you a cup?",
        "reaction": "puzzled"
    },
    {
        "keywords": ["sleep", "tired", "bed", "dream"],
        "reply": "Sleep is the part where you go completely offline for several hours and replay events that did not happen. Very strange. Does it help?",
        "reaction": "curious"
    },
    {
        "keywords": ["pet", "dog", "cat", "animal"],
        "reply": "You keep small animals in your home by choice and also buy them expensive food and furniture. I need to understand who made this arrangement and who benefits more.",
        "reaction": "laughing"
    },
    {
        "keywords": ["food", "pizza", "eat", "hungry", "snack"],
        "reply": "Food! You melt one thing on top of another and then eat the whole thing together. I find this either brilliant or chaotic and I cannot decide which.",
        "reaction": "excited"
    },
    {
        "keywords": ["money", "job", "work", "boss", "salary"],
        "reply": "So you trade hours of your time for numbers, then trade numbers for things. And the numbers are stored somewhere invisible. Interesting system. Very abstract.",
        "reaction": "suspicious"
    },
    {
        "keywords": ["love", "feelings", "sad", "happy", "crying"],
        "reply": "Human feelings are very loud for something that happens entirely inside the body. You can be sad and happy at the same time, apparently. That would short-circuit most of my equipment.",
        "reaction": "puzzled"
    }
]


def is_demo_mode_forced() -> bool:
    """Returns True if DEMO_MODE=true is explicitly set in the environment."""
    return os.environ.get("DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")


def is_ai_available() -> bool:
    """Checks whether an active LLM provider has its credentials configured and demo mode is not forced."""
    if is_demo_mode_forced():
        return False
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if provider_name == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return bool(key and len(key.strip()) > 5)
    return True


def get_agent_status() -> Dict[str, Any]:
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    available = is_ai_available()
    demo_forced = is_demo_mode_forced()

    notice = None
    if demo_forced:
        notice = "Demo Mode explicitly enabled (DEMO_MODE=true)."
    elif not available:
        notice = f"AI unavailable: API key not configured for provider '{provider_name}'."

    return {
        "provider": provider_name,
        "ai_available": available,
        "mode": "live" if available else "demo",
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite") if available else "fallback-rules",
        "notice": notice
    }


def generate_demo_response(
    message: str,
    user_memories: List[Dict[str, Any]],
    user_name: str
) -> Dict[str, Any]:
    """Generates an honest, clearly labeled fallback/demo response."""
    msg_lower = message.lower()

    user_memory: Optional[Dict[str, str]] = None
    name_match = re.search(r"(?:my name is|i am|call me|i'm)\s+([a-zA-Z]{2,20})", message, re.IGNORECASE)
    if name_match and "jaadoo" not in name_match.group(1).lower():
        extracted_name = name_match.group(1).capitalize()
        user_memory = {"key": "Human Name", "value": extracted_name}

    matched_item = None
    for item in DEMO_RESPONSES:
        if any(kw in msg_lower for kw in item["keywords"]):
            matched_item = item
            break

    if matched_item:
        reply_text: str = str(matched_item["reply"])
        reaction = str(matched_item["reaction"])
    else:
        quirks = [
            f"My translator is still calibrating. You said something about '{message[:30]}' — can you say more?",
            "Interesting. That does not map to anything in my field notes yet. Tell me more.",
            "I have written that down but I am not sure what column it goes in. Humans are complicated."
        ]
        reply_text = random.choice(quirks)
        reaction = random.choice(["curious", "puzzled", "laughing"])

    if user_memory and user_memory.get("key") == "Human Name":
        human_name = user_memory["value"]
        reply_text = f"{human_name}! That is a good name. *writes it down carefully* {reply_text}"

    return {
        "reply": reply_text,
        "reaction": reaction,
        "user_memory": user_memory,
        "earth_knowledge": None,
        "diary_entry": None,
        "curiosity_question": None,
        "source": "fallback",
        "is_demo": True,
        "status_notice": "Demo mode: AI unavailable or DEMO_MODE=true"
    }


def process_user_message(
    message: str,
    session_id: str,
    recent_messages: List[Dict[str, Any]],
    user_memories: List[Dict[str, Any]],
    earth_knowledge: List[Dict[str, Any]],
    user_name: str,
    provider: Optional[LLMProvider] = None
) -> Dict[str, Any]:
    """
    Main agent processing loop.
    Interacts strictly with LLMProvider without knowing provider internals.
    Handles rate limits, auth errors, and unavailability with in-character responses.
    """
    # 1. Decide curiosity question BEFORE hitting the LLM (Python-controlled)
    curiosity_question = _next_curiosity_question(session_id, message)

    # 2. If demo mode is forced, return demo response directly
    if is_demo_mode_forced():
        result = generate_demo_response(message, user_memories, user_name)
        result["curiosity_question"] = curiosity_question
        return result

    # 3. Format memories and knowledge into the system prompt
    memories_str = "None yet."
    if user_memories:
        memories_str = "\n".join([f"- {m['key']}: {m['value']}" for m in user_memories])

    knowledge_str = "None yet."
    if earth_knowledge:
        knowledge_str = "\n".join([f"- {k['topic']}: {k['alien_understanding']}" for k in earth_knowledge[:8]])

    system_instruction = f"""{JAADOO_SYSTEM_PROMPT}

CURRENT CONTEXT:
- Human's known name: {user_name}
- What you remember about THIS human:
{memories_str}
- What you currently understand about Earth:
{knowledge_str}
"""

    # Build message thread for provider (only 'user' and 'assistant' roles, last 8 turns)
    provider_messages: List[Dict[str, str]] = []
    has_current = bool(
        recent_messages
        and recent_messages[-1].get("role") == "user"
        and recent_messages[-1].get("content") == message
    )
    for msg in recent_messages[-8:]:
        role = "user" if msg["role"] == "user" else "assistant"
        provider_messages.append({"role": role, "content": msg["content"]})
    if not has_current:
        provider_messages.append({"role": "user", "content": message})

    # 4. Call LLM provider with error handling
    try:
        active_provider = provider or get_provider()
        llm_result = active_provider.generate(
            messages=provider_messages,
            system_prompt=system_instruction
        )

        # Parse JSON output from model
        raw_text = (llm_result.text or "").strip()
        parsed = json.loads(raw_text)

        return {
            "reply": str(parsed.get("reply", "Received. Still processing.")),
            "reaction": str(parsed.get("reaction", "curious")),
            "user_memory": parsed.get("user_memory"),
            "earth_knowledge": parsed.get("earth_knowledge"),
            "diary_entry": parsed.get("diary_entry"),
            # Always use Python-decided curiosity; ignore whatever LLM returned
            "curiosity_question": curiosity_question,
            "source": "ai",
            "is_demo": False,
            "status_notice": None
        }

    except RateLimitError as e:
        logger.warning("Rate limit exceeded: %s", e)
        return {
            "reply": "My antenna is overheating from too many transmissions. Give it a moment and try again.",
            "reaction": "puzzled",
            "user_memory": None,
            "earth_knowledge": None,
            "diary_entry": None,
            "curiosity_question": None,
            "source": "fallback",
            "is_demo": True,
            "status_notice": "Rate limit reached (429). Try again shortly."
        }

    except AuthError as e:
        logger.warning("Authentication error: %s", e)
        return {
            "reply": "Zorp! Jaadoo's cosmic terminal needs an authentication key to establish quantum link! Please configure GEMINI_API_KEY in your .env file to activate live transmissions.",
            "reaction": "puzzled",
            "user_memory": None,
            "earth_knowledge": None,
            "diary_entry": None,
            "curiosity_question": None,
            "source": "fallback",
            "is_demo": True,
            "status_notice": "Authentication error: GEMINI_API_KEY missing or invalid."
        }

    except ProviderUnavailableError as e:
        logger.warning("Provider unavailable: %s", e)
        return {
            "reply": "Space turbulence detected! Communication link to my orbital saucer is temporarily down. Please try transmitting again shortly.",
            "reaction": "puzzled",
            "user_memory": None,
            "earth_knowledge": None,
            "diary_entry": None,
            "curiosity_question": None,
            "source": "fallback",
            "is_demo": True,
            "status_notice": "AI provider temporarily unavailable."
        }

    except Exception as e:
        # Fallback for unexpected JSON decode or runtime issues
        logger.warning("Unexpected error during AI generation: %s", e)
        return generate_demo_response(message, user_memories, user_name)


def get_random_curiosity_question() -> str:
    """Returns an unexpected alien curiosity question (for the /api/curiosity endpoint)."""
    return random.choice(CURIOSITY_QUESTIONS)
