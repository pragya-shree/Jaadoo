"""
Database layer for JAADOO
Manages SQLite storage for:
1. User Memory (meaningful personal facts remembered about the user)
2. Earth Knowledge (general facts about Earth and human society decoded by Jaadoo)
3. Alien Diary (Jaadoo's personal field notes and observations about human quirks)
4. Session / Conversation chat history (persistent across browser refreshes)
"""

import os
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jaadoo.db")

def get_db_path() -> str:
    """Resolve database path, honoring Render/cloud persistent disk mounts."""
    if os.environ.get("JAADOO_DB_PATH"):
        return os.environ["JAADOO_DB_PATH"]
    if os.environ.get("DATA_DIR"):
        return os.path.join(os.environ["DATA_DIR"], "jaadoo.db")
    if os.environ.get("PERSISTENT_DIR"):
        return os.path.join(os.environ["PERSISTENT_DIR"], "jaadoo.db")
    return _DEFAULT_DB_PATH

DB_PATH = get_db_path()

SENSITIVE_KEYWORDS = {
    "password", "passwd", "pin", "credit card", "creditcard", "cvv", "ssn",
    "social security", "secret", "private key", "bank account", "api key",
    "token", "bearer", "login"
}

def get_db_connection() -> sqlite3.Connection:
    target_path = get_db_path()
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    target_path = get_db_path()
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Sessions / Conversations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        user_name TEXT DEFAULT 'Human Friend',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Additive migrations — safe to run on existing DBs
    for col, definition in [
        ("title", "TEXT DEFAULT NULL"),
        ("deleted_at", "TIMESTAMP DEFAULT NULL"),
        ("visitor_id", "TEXT DEFAULT NULL"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Chat messages history (persistent, never wiped except by user request)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        source TEXT DEFAULT 'ai',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    )
    """)
    # Ensure source column exists on older schemas
    try:
        cursor.execute("ALTER TABLE messages ADD COLUMN source TEXT DEFAULT 'ai'")
    except sqlite3.OperationalError:
        pass

    # SYSTEM 1: User Memory
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    )
    """)

    # SYSTEM 2: Earth Knowledge (global — shared across conversations)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS earth_knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT UNIQUE NOT NULL,
        alien_understanding TEXT NOT NULL,
        times_reinforced INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # SYSTEM 3: Alien Diary (global — shared across conversations)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alien_diary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        observation TEXT NOT NULL,
        confusion_level INTEGER DEFAULT 8,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    # Performance & Reliability Indexes — safe to run repeatedly
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id_asc ON messages(session_id, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_memories_session ON user_memories(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_visitor ON sessions(visitor_id)")
    conn.commit()

    # Seed initial Earth Knowledge and Alien Diary if empty
    cursor.execute("SELECT COUNT(*) FROM alien_diary")
    if cursor.fetchone()[0] == 0:
        seed_initial_data(cursor)
        conn.commit()

    conn.close()

def seed_initial_data(cursor: sqlite3.Cursor):
    seed_diary = [
        (
            "The Glowing Rectangle Worship",
            "Behaviour",
            "Humans hold thin black glass slabs inches from their ocular units for 8+ Earth hours daily. When the glass turns dark, panic ensues. May be a religious icon.",
            9
        ),
        (
            "The Birthday Cake Combustion Ritual",
            "Rituals",
            "Every 365 orbital rotations, humans place miniature fire poles atop a baked sugar disc, perform a synchronized chanting spell, blow air at the flames, and consume the fire foundation.",
            10
        ),
        (
            "Ocular Fluid Discharges",
            "Emotions",
            "Water leaks uncontrollably from human visual sensors when they experience extreme sadness, but ALSO when they experience extreme joy. My sensors find this dual-polarity mechanism highly confusing.",
            8
        ),
        (
            "Morning Bean Infusion (Coffee)",
            "Food & Sustenance",
            "Humans grind charred Earth beans into boiling dark liquid and ingest it to forcibly shock their nervous nodes awake. They warn others not to converse with them prior to ingestion.",
            7
        )
    ]
    cursor.executemany("""
    INSERT INTO alien_diary (title, category, observation, confusion_level)
    VALUES (?, ?, ?, ?)
    """, seed_diary)

    seed_knowledge = [
        ("Coffee", "Dark heated bean extraction used by humans to kickstart cellular activity after slumber.", 1),
        ("Sleep", "A biological maintenance mode where humans power down consciousness for ~8 hours under heavy fabric.", 1),
        ("Pets", "Small furry predators that humans feed and house in exchange for allowing humans to pet their fur.", 1),
        ("Money", "Printed green paper and digital numbers that humans exchange for sustenance and shelter.", 1)
    ]
    cursor.executemany("""
    INSERT OR IGNORE INTO earth_knowledge (topic, alien_understanding, times_reinforced)
    VALUES (?, ?, ?)
    """, seed_knowledge)

# ==================== SESSIONS / CONVERSATIONS ====================

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch an active session by session_id, or None if deleted/nonexistent."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_id = ? AND deleted_at IS NULL", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_or_create_session(
    session_id: str,
    user_name: str = "Human Friend",
    visitor_id: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve or create a session. Associates visitor_id for ownership."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO sessions (session_id, user_name, visitor_id) VALUES (?, ?, ?)",
            (session_id, user_name, visitor_id)
        )
        conn.commit()
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
    else:
        # If session was previously soft-deleted, reactivate it fresh
        if row["deleted_at"] is not None:
            cursor.execute(
                "UPDATE sessions SET deleted_at = NULL, user_name = ?, last_active = CURRENT_TIMESTAMP, title = NULL, visitor_id = COALESCE(?, visitor_id) WHERE session_id = ?",
                (user_name, visitor_id, session_id)
            )
        elif visitor_id and not row["visitor_id"]:
            cursor.execute(
                "UPDATE sessions SET last_active = CURRENT_TIMESTAMP, visitor_id = ? WHERE session_id = ?",
                (visitor_id, session_id)
            )
        else:
            cursor.execute(
                "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )
        conn.commit()
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
    result = dict(row)
    conn.close()
    return result

def get_all_conversations(visitor_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Return non-deleted conversations, most recently active first.
    If visitor_id is provided, returns ONLY conversations belonging to that visitor.
    If visitor_id is None, returns conversations without a visitor_id (or all for backward compat).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    if visitor_id:
        cursor.execute("""
            SELECT s.session_id, s.user_name, s.title, s.created_at, s.last_active, s.visitor_id,
                   COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.session_id
            WHERE s.deleted_at IS NULL AND s.visitor_id = ?
            GROUP BY s.session_id
            ORDER BY s.last_active DESC
            LIMIT ?
        """, (visitor_id, limit))
    else:
        cursor.execute("""
            SELECT s.session_id, s.user_name, s.title, s.created_at, s.last_active, s.visitor_id,
                   COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.session_id
            WHERE s.deleted_at IS NULL
            GROUP BY s.session_id
            ORDER BY s.last_active DESC
            LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_conversation_title(session_id: str, title: str) -> bool:
    """Set or update the display title for a conversation."""
    clean = title.strip()[:80] if title else None
    if not clean:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET title = ? WHERE session_id = ? AND deleted_at IS NULL",
        (clean, session_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def delete_conversation(session_id: str) -> bool:
    """Soft-delete a conversation (and hard-delete its messages/memories)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Hard-delete messages and memories so storage is reclaimed
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM user_memories WHERE session_id = ?", (session_id,))
    # Soft-delete the session so the session_id is never reused
    cursor.execute(
        "UPDATE sessions SET deleted_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_conversation_messages(session_id: str) -> List[Dict[str, Any]]:
    """Return full message history for a conversation in chronological order."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, role, content, source, timestamp
        FROM messages
        WHERE session_id = ?
        ORDER BY id ASC
    """, (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_last_message(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent message in a session, or None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, role, content, source, timestamp
        FROM messages
        WHERE session_id = ?
        ORDER BY id DESC LIMIT 1
    """, (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_message(session_id: str, role: str, content: str, source: str = "ai"):
    """Persist a message and bump the conversation's last_active timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, source) VALUES (?, ?, ?, ?)",
        (session_id, role, content, source)
    )
    cursor.execute(
        "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,)
    )
    conn.commit()
    conn.close()

def get_recent_messages(session_id: str, limit: int = 12, exclude_fallback: bool = False) -> List[Dict[str, Any]]:
    """Fetch recent messages for context window, in chronological order."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if exclude_fallback:
        cursor.execute("""
        SELECT role, content, source, timestamp FROM messages
        WHERE session_id = ? AND source != 'fallback'
        ORDER BY id DESC LIMIT ?
        """, (session_id, limit))
    else:
        cursor.execute("""
        SELECT role, content, source, timestamp FROM messages
        WHERE session_id = ?
        ORDER BY id DESC LIMIT ?
        """, (session_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def clear_session_messages(session_id: str):
    """Clears messages for the current session (resets conversation)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("UPDATE sessions SET title = NULL WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

# ==================== SYSTEM 1: USER MEMORY ====================

def is_sensitive(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in SENSITIVE_KEYWORDS)

def save_user_memory(session_id: str, key: str, value: str) -> Optional[int]:
    """Store only meaningful, non-sensitive memories about the user."""
    if not key or not value:
        return None
    if is_sensitive(key) or is_sensitive(value):
        return None

    clean_key = key.strip()[:60]
    clean_val = value.strip()[:200]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM user_memories WHERE session_id = ? AND LOWER(key) = LOWER(?)", (session_id, clean_key))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE user_memories SET value = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?", (clean_val, existing["id"]))
        mem_id = existing["id"]
    else:
        cursor.execute("INSERT INTO user_memories (session_id, key, value) VALUES (?, ?, ?)", (session_id, clean_key, clean_val))
        mem_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return mem_id

def get_user_memories(session_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, key, value, created_at FROM user_memories
    WHERE session_id = ?
    ORDER BY created_at DESC
    """, (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_user_memory(memory_id: int, session_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_memories WHERE id = ? AND session_id = ?", (memory_id, session_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

# ==================== SYSTEM 2: EARTH KNOWLEDGE ====================

def save_earth_knowledge(topic: str, alien_understanding: str) -> Optional[int]:
    """Store general concepts about Earth synthesized from conversations."""
    if not topic or not alien_understanding or is_sensitive(topic) or is_sensitive(alien_understanding):
        return None

    clean_topic = topic.strip().title()[:60]
    clean_understanding = alien_understanding.strip()[:300]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, times_reinforced FROM earth_knowledge WHERE LOWER(topic) = LOWER(?)", (clean_topic,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("""
        UPDATE earth_knowledge
        SET alien_understanding = ?, times_reinforced = times_reinforced + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (clean_understanding, existing["id"]))
        k_id = existing["id"]
    else:
        cursor.execute("""
        INSERT INTO earth_knowledge (topic, alien_understanding, times_reinforced)
        VALUES (?, ?, 1)
        """, (clean_topic, clean_understanding))
        k_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return k_id

def get_all_earth_knowledge() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, topic, alien_understanding, times_reinforced, updated_at
    FROM earth_knowledge
    ORDER BY updated_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ==================== SYSTEM 3: ALIEN DIARY ====================

def save_diary_entry(title: str, category: str, observation: str, confusion_level: int = 8) -> Optional[int]:
    """Store Jaadoo's personal quirky field observations."""
    if not title or not observation:
        return None

    clean_title = title.strip()[:80]
    clean_category = category.strip()[:40] or "Field Notes"
    clean_obs = observation.strip()[:400]
    confusion = max(1, min(10, confusion_level))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM alien_diary WHERE LOWER(title) = LOWER(?)", (clean_title,))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("""
        UPDATE alien_diary
        SET observation = ?, confusion_level = ?, category = ?, created_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """, (clean_obs, confusion, clean_category, existing["id"]))
        d_id = existing["id"]
    else:
        cursor.execute("""
        INSERT INTO alien_diary (title, category, observation, confusion_level)
        VALUES (?, ?, ?, ?)
        """, (clean_title, clean_category, clean_obs, confusion))
        d_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return d_id

def get_all_diary_entries() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, title, category, observation, confusion_level, created_at
    FROM alien_diary
    ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ==================== BACKUP & RECOVERY ====================

def backup_db(target_path: Optional[str] = None) -> str:
    """
    Creates an online, consistent SQLite backup using the native SQLite backup API.
    Does not lock out readers or writers during execution.
    """
    if not target_path:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(os.path.dirname(get_db_path()), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        target_path = os.path.join(backup_dir, f"jaadoo_backup_{ts}.db")
    else:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

    src_conn = get_db_connection()
    dst_conn = sqlite3.connect(target_path)
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()
    return target_path
