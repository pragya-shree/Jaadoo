"""
Automated Backend Test Suite for JAADOO
Tests:
- Database schema and 3 distinct systems (Memory, Knowledge, Diary)
- Personality & Demo/AI agent fallback
- FastAPI endpoints (status, chat, memories, diary, earth-knowledge, curiosity, reset)
"""

import sys
import os

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import (
    get_status,
    chat_endpoint,
    get_memories,
    delete_memory,
    get_diary,
    get_earth_knowledge,
    get_curiosity,
    reset_session,
    ChatRequest,
    MemoryDeleteRequest
)
from backend import database as db
from backend import agent

def test_database_systems():
    print("Testing Database Systems...")
    db.init_db()
    
    # Check System 3 (Alien Diary)
    diary = db.get_all_diary_entries()
    assert len(diary) >= 4, f"Expected at least 4 diary entries, got {len(diary)}"
    print(f"  [PASS] System 3 (Alien Diary): {len(diary)} entries verified.")

    # Check System 2 (Earth Knowledge)
    knowledge = db.get_all_earth_knowledge()
    assert len(knowledge) >= 4, f"Expected at least 4 knowledge entries, got {len(knowledge)}"
    print(f"  [PASS] System 2 (Earth Knowledge): {len(knowledge)} entries verified.")

    # Check System 1 (User Memory)
    session_id = "test_sess_001"
    # Ensure sensitive info is rejected
    assert db.save_user_memory(session_id, "password", "12345") is None, "Sensitive data was not blocked!"
    assert db.save_user_memory(session_id, "credit card", "41112222") is None, "Sensitive data was not blocked!"
    
    # Store meaningful memory
    mem_id = db.save_user_memory(session_id, "Favorite Food", "Spicy Ramen")
    assert mem_id is not None, "Failed to save valid user memory"
    memories = db.get_user_memories(session_id)
    assert any(m["key"] == "Favorite Food" for m in memories)
    print(f"  [PASS] System 1 (User Memory): Non-sensitive filtering and storage verified.")

def test_agent_logic():
    print("Testing Agent Logic & Personality...")
    # Demo response test
    res = agent.generate_demo_response("My name is Zora and I love coffee", [], "Human")
    assert res["reply"] is not None
    assert res["is_demo"] is True
    assert res["source"] == "fallback"
    assert res["earth_knowledge"] is None
    assert res["diary_entry"] is None
    print(f"  [PASS] Demo Mode: Generated in-character fallback response with knowledge guardrail.")

    # Curiosity question test
    q = agent.get_random_curiosity_question()
    assert len(q) > 10
    print(f"  [PASS] Curiosity Engine: '{q[:40]}...' generated.")

def test_api_endpoints():
    print("Testing FastAPI Route Handlers...")

    # 1. Status
    status_data = get_status()
    assert "mode" in status_data
    assert "counts" in status_data
    print(f"  [PASS] GET /api/status -> mode: {status_data['mode']}, counts: {status_data['counts']}")

    # 2. Chat with fallback handling
    sess = "api_test_session_42"
    chat_data = chat_endpoint(ChatRequest(
        session_id=sess,
        message="My name is Carlos and I am curious about cats and dogs",
        user_name="Carlos"
    ))
    assert "reply" in chat_data
    assert "reaction" in chat_data
    assert chat_data["source"] in ("ai", "fallback")
    print(f"  [PASS] POST /api/chat -> Jaadoo replied (source: {chat_data['source']}, reaction: {chat_data['reaction']})")

    # 3. User Memories storage & retrieval
    db.save_user_memory(sess, "Hobby", "Stargazing")
    mems = get_memories(session_id=sess)
    assert len(mems) >= 1
    print(f"  [PASS] GET /api/memories -> Retrieved {len(mems)} memories for session.")

    # 4. Retrieve Alien Diary
    diary = get_diary()
    assert len(diary) >= 4
    print(f"  [PASS] GET /api/diary -> Retrieved {len(diary)} field observations.")

    # 5. Retrieve Earth Knowledge
    knowledge = get_earth_knowledge()
    assert len(knowledge) >= 4
    print(f"  [PASS] GET /api/earth-knowledge -> Retrieved {len(knowledge)} concepts.")

    # 6. Curiosity endpoint
    curiosity = get_curiosity()
    assert "question" in curiosity
    print(f"  [PASS] GET /api/curiosity -> '{curiosity['question'][:45]}...'")

    # 7. Delete Memory (privacy test)
    mem_to_delete = mems[0]["id"]
    del_res = delete_memory(memory_id=mem_to_delete, session_id=sess)
    assert del_res["status"] == "deleted"
    mems_after = get_memories(session_id=sess)
    assert not any(m["id"] == mem_to_delete for m in mems_after)
    print(f"  [PASS] DELETE /api/memories/{mem_to_delete} -> Privacy deletion verified.")

    # 8. Reset session
    reset_res = reset_session(MemoryDeleteRequest(session_id=sess))
    assert reset_res["status"] == "reset"
    print("  [PASS] POST /api/reset -> Session message history cleared.")

def test_navigation_and_assets():
    print("Testing Navigation & Static Assets...")
    from backend.main import serve_index, serve_chat, BASE_DIR

    # 1. Verify index.html contains correct navigation href
    index_res = serve_index()
    assert os.path.exists(index_res.path)
    with open(index_res.path, "r", encoding="utf-8") as f:
        index_content = f.read()
    assert 'href="chat.html">MEET JAADOO</a>' in index_content
    print("  [PASS] index.html: 'MEET JAADOO' button correctly points to 'chat.html'.")

    # 2. Verify chat.html is served and valid
    chat_res = serve_chat()
    assert os.path.exists(chat_res.path)
    with open(chat_res.path, "r", encoding="utf-8") as f:
        chat_content = f.read()
    assert 'composerInput' in chat_content
    assert 'js/chat.js' in chat_content
    print("  [PASS] chat.html: Correctly served with complete interactive UI elements.")

    # 3. Verify CSS and JS assets
    required_assets = [
        "css/styles.css",
        "css/chat.css",
        "js/main.js",
        "js/chat.js",
        "assets/images/jaadoo-alien.jpg",
        "assets/images/space-nebula.jpg"
    ]
    for asset in required_assets:
        full_path = os.path.join(BASE_DIR, asset)
        assert os.path.exists(full_path), f"Missing asset: {asset}"
    print(f"  [PASS] All {len(required_assets)} frontend assets verified on disk.")

if __name__ == "__main__":
    try:
        test_database_systems()
        test_agent_logic()
        test_api_endpoints()
        test_navigation_and_assets()
        print("\n>>> ALL BACKEND & NAVIGATION TESTS PASSED SUCCESSFULLY! <<<")
    except Exception as e:
        print(f"\n[FAIL] Test encountered an error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
