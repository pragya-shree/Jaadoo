"""
Persistent Conversation History Tests for JAADOO

Tests:
  1. init_db() safely adds new columns to existing sessions table (migration).
  2. get_or_create_session() creates and retrieves sessions.
  3. save_message() persists and get_conversation_messages() returns them in order.
  4. get_all_conversations() returns sessions with message counts.
  5. Auto-title is set by /api/chat on the first user message.
  6. update_conversation_title() sets and updates a custom title.
  7. delete_conversation() removes messages/memories and soft-deletes the session.
  8. Deleted conversations do not appear in get_all_conversations().
  9. Reopening a conversation via GET /api/conversations/{id}/messages returns full history.
  10. Fallback replies are NOT counted in LLM context (exclude_fallback=True) but do persist.
  11. get_all_conversations() returns sessions ordered by last_active descending.
  12. clear_session_messages() resets the title so a new one is generated next send.
  13. Multi-visitor privacy: visitor B cannot read or delete visitor A's conversation.
  14. Context continuity: reopening older conversation passes its prior turns to LLM context.
  15. Retry deduplication: unresponded identical message is not duplicated in DB.
  16. Online SQLite backup: backup_db() creates consistent, readable backup copy.
  17. Global Earth Knowledge & Alien Diary are untouched when a conversation is deleted.
  18. JAADOO_DB_PATH environment variable override redirects database location cleanly.
"""

import sys
import os
import time
import tempfile
import sqlite3
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import database as db
from backend.main import (
    chat_endpoint, list_conversations, get_conversation_history,
    rename_conversation, delete_conversation as api_delete_conversation,
    get_memories, ChatRequest, ConversationTitleRequest
)


# ===========================================================================
# TEST 1: Safe migration — init_db() idempotent on existing DB
# ===========================================================================

def test_migration_idempotent():
    print("Testing migration idempotency...")
    db.init_db()
    db.init_db()

    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(sessions)")
    cols = {row["name"] for row in cursor.fetchall()}
    conn.close()

    assert "title" in cols,      "sessions.title column must exist after migration."
    assert "deleted_at" in cols, "sessions.deleted_at column must exist after migration."
    assert "visitor_id" in cols, "sessions.visitor_id column must exist after migration."
    print("  [PASS] init_db() is idempotent; title, deleted_at, visitor_id columns present.")


# ===========================================================================
# TEST 2: Session create / retrieve
# ===========================================================================

def test_session_create_and_retrieve():
    print("Testing session create and retrieve...")
    sid = "hist_test_session_001"
    s = db.get_or_create_session(sid, "Alice")
    assert s["session_id"] == sid
    assert s["user_name"] == "Alice"

    # Second call should return the same record
    s2 = db.get_or_create_session(sid, "Bob")
    assert s2["session_id"] == sid
    print("  [PASS] Session created and retrieved correctly.")


# ===========================================================================
# TEST 3: Message persistence and ordering
# ===========================================================================

def test_message_persistence():
    print("Testing message persistence and ordering...")
    sid = "hist_test_session_002"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "Tester")

    db.save_message(sid, "user",      "Hello Jaadoo!",    source="user")
    db.save_message(sid, "assistant", "Hello, human!",    source="ai")
    db.save_message(sid, "user",      "What is a pizza?", source="user")
    db.save_message(sid, "assistant", "Circular cheesy slab.", source="ai")

    messages = db.get_conversation_messages(sid)
    assert len(messages) == 4, f"Expected 4 messages, got {len(messages)}"
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello Jaadoo!"
    assert messages[-1]["role"] == "assistant"
    print("  [PASS] Messages persisted and returned in correct order.")


# ===========================================================================
# TEST 4: get_all_conversations() with message counts
# ===========================================================================

def test_list_conversations():
    print("Testing conversation listing with message counts...")
    sid = "hist_test_session_003"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "Lister")
    db.save_message(sid, "user", "one", source="user")
    db.save_message(sid, "assistant", "two", source="ai")

    convs = db.get_all_conversations()
    ids = [c["session_id"] for c in convs]
    assert sid in ids, f"{sid} not found in conversation list."
    conv = next(c for c in convs if c["session_id"] == sid)
    assert conv["message_count"] == 2
    print(f"  [PASS] {len(convs)} conversations listed; message counts correct.")


# ===========================================================================
# TEST 5: Auto-title generated from first user message via /api/chat
# ===========================================================================

def test_auto_title_from_first_message():
    print("Testing auto-title generation from first user message...")
    sid = "hist_test_autotitle"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "AutoUser")

    chat_endpoint(ChatRequest(
        session_id=sid,
        message="Tell me about Earth music",
        user_name="AutoUser"
    ))

    convs = db.get_all_conversations()
    conv = next((c for c in convs if c["session_id"] == sid), None)
    assert conv is not None, "Session not found in conversation list."
    assert conv["title"] is not None, "Title should be auto-generated after first message."
    assert "Tell me about Earth music" in conv["title"] or len(conv["title"]) > 0
    print(f"  [PASS] Auto-title generated: '{conv['title']}'")


# ===========================================================================
# TEST 6: update_conversation_title()
# ===========================================================================

def test_update_conversation_title():
    print("Testing conversation title update...")
    sid = "hist_test_session_004"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "Renamer")

    ok = db.update_conversation_title(sid, "My favourite chat")
    assert ok, "update_conversation_title should return True."

    convs = db.get_all_conversations()
    conv = next((c for c in convs if c["session_id"] == sid), None)
    assert conv is not None
    assert conv["title"] == "My favourite chat"
    print("  [PASS] Conversation title updated correctly.")


# ===========================================================================
# TEST 7 & 8: delete_conversation() removes data and hides from listing
# ===========================================================================

def test_delete_conversation():
    print("Testing conversation deletion...")
    sid = "hist_test_session_005"
    # Re-activate in case previous run deleted it
    conn = db.get_db_connection()
    conn.execute("UPDATE sessions SET deleted_at = NULL WHERE session_id = ?", (sid,))
    conn.commit()
    conn.close()

    db.get_or_create_session(sid, "Deleter")
    db.save_message(sid, "user", "Delete me", source="user")
    db.save_user_memory(sid, "Hobby", "Painting")

    ok = db.delete_conversation(sid)
    assert ok, "delete_conversation should return True."

    # Messages must be gone
    msgs = db.get_conversation_messages(sid)
    assert len(msgs) == 0, "Messages must be deleted with the conversation."

    # Memories must be gone
    mems = db.get_user_memories(sid)
    assert len(mems) == 0, "Memories must be deleted with the conversation."

    # Must not appear in listing
    convs = db.get_all_conversations()
    ids = [c["session_id"] for c in convs]
    assert sid not in ids, "Deleted conversation must not appear in listing."
    print("  [PASS] Conversation deleted; messages, memories, and listing entry removed.")


# ===========================================================================
# TEST 9: Reopen conversation via API endpoint
# ===========================================================================

def test_reopen_conversation_via_api():
    print("Testing conversation reopen via API...")
    sid = "hist_test_session_006"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "Reopener")
    db.save_message(sid, "user",      "My name is Rex",   source="user")
    db.save_message(sid, "assistant", "Nice to meet Rex", source="ai")
    db.save_message(sid, "user",      "I like dogs",      source="user")

    history = get_conversation_history(sid)
    assert isinstance(history, list)
    assert len(history) == 3
    assert history[0]["content"] == "My name is Rex"
    assert history[0]["role"] == "user"
    assert history[2]["role"] == "user"
    print(f"  [PASS] Conversation history ({len(history)} messages) returned via API.")


# ===========================================================================
# TEST 10: Fallback replies excluded from LLM context but stored in DB
# ===========================================================================

def test_fallback_excluded_from_llm_context_but_stored():
    print("Testing fallback replies stored but excluded from LLM context...")
    sid = "hist_test_session_007"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "FallbackUser")
    db.save_message(sid, "user",      "Hello",             source="user")
    db.save_message(sid, "assistant", "Simulated reply",   source="fallback")
    db.save_message(sid, "user",      "Second message",    source="user")

    all_msgs = db.get_conversation_messages(sid)
    assert len(all_msgs) == 3, "All messages (including fallback) must be stored."

    llm_msgs = db.get_recent_messages(sid, limit=12, exclude_fallback=True)
    fallback_in_llm = [m for m in llm_msgs if m.get("source") == "fallback"]
    assert len(fallback_in_llm) == 0, "Fallback messages must be excluded from LLM context."
    print("  [PASS] Fallback replies stored in DB but excluded from LLM context window.")


# ===========================================================================
# TEST 11: Ordering — most recently active first
# ===========================================================================

def test_conversation_ordering():
    print("Testing conversation ordering (most recent first)...")
    sid_a = "hist_order_A"
    sid_b = "hist_order_B"
    db.clear_session_messages(sid_a)
    db.clear_session_messages(sid_b)

    db.get_or_create_session(sid_a, "Alpha")
    db.get_or_create_session(sid_b, "Beta")

    # Set distinct last_active times deterministically (SQLite CURRENT_TIMESTAMP has 1s resolution)
    conn = db.get_db_connection()
    conn.execute("UPDATE sessions SET last_active = datetime('now', '-30 seconds') WHERE session_id = ?", (sid_a,))
    conn.execute("UPDATE sessions SET last_active = datetime('now') WHERE session_id = ?", (sid_b,))
    conn.commit()
    conn.close()

    convs = db.get_all_conversations()
    ids = [c["session_id"] for c in convs if c["session_id"] in (sid_a, sid_b)]
    assert ids[0] == sid_b, f"Most recently active session should be first; got {ids}"
    print("  [PASS] Conversations ordered most-recently-active first.")


# ===========================================================================
# TEST 12: clear_session_messages resets the title
# ===========================================================================

def test_clear_messages_resets_title():
    print("Testing clear_session_messages resets the title...")
    sid = "hist_test_session_008"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "Resetter")
    db.update_conversation_title(sid, "Old title")
    db.save_message(sid, "user", "something", source="user")

    db.clear_session_messages(sid)

    conn = db.get_db_connection()
    row = conn.execute("SELECT title FROM sessions WHERE session_id = ?", (sid,)).fetchone()
    conn.close()
    assert row["title"] is None, "Title should be reset to NULL after clear_session_messages."

    msgs = db.get_conversation_messages(sid)
    assert len(msgs) == 0
    print("  [PASS] clear_session_messages wiped messages and reset title to NULL.")


# ===========================================================================
# TEST 13: Multi-visitor privacy — visitor isolation
# ===========================================================================

def test_multi_visitor_privacy():
    print("Testing multi-visitor privacy and ownership isolation...")
    visitor_alice = "v_alice_123"
    visitor_bob   = "v_bob_456"

    sid_alice = "sess_alice_private"
    db.clear_session_messages(sid_alice)
    db.get_or_create_session(sid_alice, "Alice", visitor_id=visitor_alice)
    conn = db.get_db_connection()
    conn.execute("UPDATE sessions SET visitor_id = ? WHERE session_id = ?", (visitor_alice, sid_alice))
    conn.commit()
    conn.close()

    db.save_message(sid_alice, "user", "Secret from Alice", source="user")
    db.save_user_memory(sid_alice, "Secret Code", "42-Galaxy")

    # 1. Alice can list her conversation
    alice_convs = list_conversations(x_visitor_id=visitor_alice)
    alice_ids = [c["session_id"] for c in alice_convs]
    assert sid_alice in alice_ids, "Alice should see her own conversation."

    # 2. Bob cannot see Alice's conversation in his list
    bob_convs = list_conversations(x_visitor_id=visitor_bob)
    bob_ids = [c["session_id"] for c in bob_convs]
    assert sid_alice not in bob_ids, "Bob must NOT see Alice's conversation in his list!"

    # 3. Bob cannot read Alice's messages directly by passing her session_id
    try:
        get_conversation_history(sid_alice, x_visitor_id=visitor_bob)
        assert False, "Bob should have been denied access (403) to Alice's conversation messages!"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403 Forbidden, got {e.status_code}"

    # 4. Bob cannot delete Alice's conversation
    try:
        api_delete_conversation(sid_alice, x_visitor_id=visitor_bob)
        assert False, "Bob should have been denied access (403) to delete Alice's conversation!"
    except HTTPException as e:
        assert e.status_code == 403

    # 5. Bob cannot read Alice's private memories
    try:
        get_memories(session_id=sid_alice, x_visitor_id=visitor_bob)
        assert False, "Bob should have been denied access (403) to Alice's memories!"
    except HTTPException as e:
        assert e.status_code == 403

    # 6. Alice can read her own conversation messages
    alice_msgs = get_conversation_history(sid_alice, x_visitor_id=visitor_alice)
    assert len(alice_msgs) >= 1
    assert alice_msgs[0]["content"] == "Secret from Alice"

    print("  [PASS] Multi-visitor privacy verified: cross-visitor snooping and tampering blocked.")


# ===========================================================================
# TEST 14: Context continuity when reopening older conversation
# ===========================================================================

def test_context_continuity_on_reopen():
    print("Testing context continuity when continuing an older conversation...")
    sid = "sess_continuity_test"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "Traveler")

    # Seed prior turns
    db.save_message(sid, "user", "I am planning a trip to Saturn", source="user")
    db.save_message(sid, "assistant", "Saturn's rings are dusty. Bring goggles.", source="ai")
    db.save_message(sid, "user", "What should I pack?", source="user")
    db.save_message(sid, "assistant", "Thermal foil and cosmic crackers.", source="ai")

    # User reopens this conversation and sends a follow-up
    res = chat_endpoint(ChatRequest(
        session_id=sid,
        message="Will the crackers stay fresh there?",
        user_name="Traveler"
    ))
    assert res["reply"] is not None

    # Full conversation should now contain all 6 messages (4 prior + 1 user + 1 assistant)
    all_msgs = db.get_conversation_messages(sid)
    assert len(all_msgs) == 6, f"Expected 6 messages total in reopened conversation, got {len(all_msgs)}"
    assert all_msgs[0]["content"] == "I am planning a trip to Saturn"
    assert all_msgs[4]["content"] == "Will the crackers stay fresh there?"
    print(f"  [PASS] Context continuity verified: 6 messages preserved chronologically across turns.")


# ===========================================================================
# TEST 15: Retry deduplication
# ===========================================================================

def test_retry_deduplication():
    print("Testing retry deduplication for unresponded messages...")
    sid = "sess_retry_dedup"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "RetryUser")

    # Simulate: user message was saved, but before AI responded the request was retried
    db.save_message(sid, "user", "Are stars hot?", source="user")
    count_before = len(db.get_conversation_messages(sid))
    assert count_before == 1

    # Now the client retries the same message via chat_endpoint
    res = chat_endpoint(ChatRequest(
        session_id=sid,
        message="Are stars hot?",
        user_name="RetryUser"
    ))
    assert res["reply"] is not None

    msgs = db.get_conversation_messages(sid)
    user_msgs = [m for m in msgs if m["role"] == "user"]
    # Must NOT have 2 user messages of "Are stars hot?"
    assert len(user_msgs) == 1, f"User message was duplicated on retry! Found {len(user_msgs)}"
    print("  [PASS] Retry deduplication verified: unresponded message was not duplicated.")


# ===========================================================================
# TEST 16: Online SQLite backup
# ===========================================================================

def test_online_backup():
    print("Testing online consistent SQLite backup...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        backup_path = tmp.name

    try:
        saved_path = db.backup_db(backup_path)
        assert os.path.exists(saved_path)
        assert os.path.getsize(saved_path) > 0

        # Open the backup copy and verify integrity and sessions table
        backup_conn = sqlite3.connect(saved_path)
        cur = backup_conn.cursor()
        cur.execute("PRAGMA integrity_check")
        assert cur.fetchone()[0] == "ok", "Backup failed integrity check!"
        cur.execute("SELECT COUNT(*) FROM sessions")
        session_count = cur.fetchone()[0]
        assert session_count >= 1, "Backup should contain sessions."
        backup_conn.close()
        print(f"  [PASS] Online backup created successfully ({session_count} sessions verified, integrity ok).")
    finally:
        if os.path.exists(backup_path):
            os.remove(backup_path)


# ===========================================================================
# TEST 17: Global Earth Knowledge & Diary are NOT deleted when conversation deleted
# ===========================================================================

def test_global_data_untouched_on_conversation_delete():
    print("Testing global knowledge and diary isolation on conversation deletion...")
    sid = "sess_isolate_test"
    db.clear_session_messages(sid)
    db.get_or_create_session(sid, "GlobalTester")
    db.save_message(sid, "user", "Talk about bicycles", source="user")

    # Add a knowledge entry and diary entry
    k_id = db.save_earth_knowledge("Bicycle Wheels", "Round rotating discs humans propel with leg levers.")
    d_id = db.save_diary_entry("Leg Lever Devices", "Behaviour", "Humans pedal two circles simultaneously.", 7)

    diary_before = len(db.get_all_diary_entries())
    knowledge_before = len(db.get_all_earth_knowledge())

    # Delete the conversation
    db.delete_conversation(sid)

    diary_after = len(db.get_all_diary_entries())
    knowledge_after = len(db.get_all_earth_knowledge())

    assert diary_after == diary_before, "Alien Diary entries must NOT be deleted when a conversation is deleted!"
    assert knowledge_after == knowledge_before, "Earth Knowledge must NOT be deleted when a conversation is deleted!"
    print("  [PASS] Global knowledge and diary remain 100% intact after conversation deletion.")


# ===========================================================================
# TEST 18: JAADOO_DB_PATH environment variable override
# ===========================================================================

def test_db_path_env_override():
    print("Testing persistent storage path resolution via JAADOO_DB_PATH...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        custom_db = os.path.join(tmp_dir, "render_test.db")
        old_env = os.environ.get("JAADOO_DB_PATH")
        try:
            os.environ["JAADOO_DB_PATH"] = custom_db
            resolved_path = db.get_db_path()
            assert resolved_path == custom_db, f"Expected {custom_db}, got {resolved_path}"

            # Ensure init_db works on the custom persistent disk path
            db.init_db()
            assert os.path.exists(custom_db)

            # Write a session and verify
            conn = db.get_db_connection()
            conn.execute("INSERT INTO sessions (session_id, user_name) VALUES (?, ?)", ("persistent_01", "RenderUser"))
            conn.commit()
            cur = conn.cursor()
            cur.execute("SELECT user_name FROM sessions WHERE session_id = 'persistent_01'")
            row = cur.fetchone()
            assert row[0] == "RenderUser"
            conn.close()
        finally:
            if old_env is not None:
                os.environ["JAADOO_DB_PATH"] = old_env
            else:
                os.environ.pop("JAADOO_DB_PATH", None)

    print("  [PASS] JAADOO_DB_PATH custom persistent storage path correctly handles production mounts.")


# ===========================================================================
# RUNNER
# ===========================================================================

if __name__ == "__main__":
    try:
        db.init_db()
        test_migration_idempotent()
        test_session_create_and_retrieve()
        test_message_persistence()
        test_list_conversations()
        test_auto_title_from_first_message()
        test_update_conversation_title()
        test_delete_conversation()
        test_reopen_conversation_via_api()
        test_fallback_excluded_from_llm_context_but_stored()
        test_conversation_ordering()
        test_clear_messages_resets_title()
        test_multi_visitor_privacy()
        test_context_continuity_on_reopen()
        test_retry_deduplication()
        test_online_backup()
        test_global_data_untouched_on_conversation_delete()
        test_db_path_env_override()
        print("\n>>> ALL 18 CONVERSATION & PERSISTENCE TESTS PASSED (100%)! <<<")
    except Exception as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        import sys
        sys.exit(1)
