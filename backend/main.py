"""
FastAPI Server for JAADOO
Coordinates:
- Static file serving (Landing page + Chat app + Assets)
- Real-time conversation orchestration
- Three distinct storage systems (User Memory, Earth Knowledge, Alien Diary)
- Persistent conversation history with list, reopen, rename and delete
- Multi-visitor privacy and ownership validation
- Transparent Live AI vs Demo Mode handling
"""

import os
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import database as db
from backend import agent

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="JAADOO AI Alien Agent", version="1.0.0")

# Enable CORS for local development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on import/startup
db.init_db()

# Request schemas
class ChatRequest(BaseModel):
    session_id: str
    message: str
    user_name: Optional[str] = "Human Friend"
    visitor_id: Optional[str] = None

class MemoryDeleteRequest(BaseModel):
    session_id: str
    visitor_id: Optional[str] = None

class ConfigKeyRequest(BaseModel):
    api_key: str

class ConversationTitleRequest(BaseModel):
    title: str

def _clean_str(val: Any) -> Optional[str]:
    """Safely extracts a non-empty string, ignoring FastAPI Header/Query param objects when called directly."""
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None

# Helper to verify session ownership
def _verify_session_access(session: Optional[Dict[str, Any]], visitor_id: Optional[str]):
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    owner = session.get("visitor_id")
    vid = _clean_str(visitor_id)
    if owner and vid and owner != vid:
        raise HTTPException(status_code=403, detail="Access denied: this conversation belongs to another visitor.")

# ==================== API ROUTES ====================

@app.get("/api/status")
def get_status(
    session_id: Optional[str] = None,
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id")
):
    status = agent.get_agent_status()
    diary_count = len(db.get_all_diary_entries())
    knowledge_count = len(db.get_all_earth_knowledge())
    memories_count = 0
    vid = _clean_str(x_visitor_id)
    if session_id:
        session = db.get_session(session_id)
        if session:
            # Only count memories if authorized or session is unassigned
            if not session.get("visitor_id") or not vid or session["visitor_id"] == vid:
                memories_count = len(db.get_user_memories(session_id))
    return {
        **status,
        "counts": {
            "diary_entries": diary_count,
            "earth_knowledge": knowledge_count,
            "user_memories": memories_count
        }
    }

@app.post("/api/chat")
def chat_endpoint(
    req: ChatRequest,
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id")
):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    effective_visitor_id = _clean_str(req.visitor_id) or _clean_str(x_visitor_id)

    # Check ownership if session already exists
    existing_session = db.get_session(req.session_id)
    if existing_session and existing_session.get("visitor_id"):
        if effective_visitor_id and existing_session["visitor_id"] != effective_visitor_id:
            raise HTTPException(status_code=403, detail="Access denied: conversation belongs to another visitor.")

    session = db.get_or_create_session(
        req.session_id,
        req.user_name or "Human Friend",
        visitor_id=effective_visitor_id
    )

    # Check for retry deduplication: if the last message in this session is an identical
    # user message that hasn't received an assistant reply yet, reuse it instead of duplicating
    last_msg = db.get_last_message(req.session_id)
    is_retry = bool(
        last_msg
        and last_msg.get("role") == "user"
        and last_msg.get("content", "").strip() == req.message.strip()
    )
    if not is_retry:
        db.save_message(req.session_id, "user", req.message, source="user")

    # Auto-generate a title from the first user message if none exists yet
    if not session.get("title"):
        raw_title = req.message.strip()
        title = (raw_title[:47] + "...") if len(raw_title) > 50 else raw_title
        db.update_conversation_title(req.session_id, title)

    # Retrieve relevant context (excluding any previous fallback/demo turns)
    recent_messages = db.get_recent_messages(req.session_id, limit=8, exclude_fallback=True)
    user_memories = db.get_user_memories(req.session_id)
    earth_knowledge = db.get_all_earth_knowledge()

    # Process through Agent personality engine (which coordinates LLMProvider)
    result = agent.process_user_message(
        message=req.message,
        session_id=req.session_id,
        recent_messages=recent_messages,
        user_memories=user_memories,
        earth_knowledge=earth_knowledge,
        user_name=session.get("user_name", "Human Friend")
    )

    reply_text = result.get("reply", "Zorp! My communicator experienced static.")
    reaction = result.get("reaction", "curious")
    source = result.get("source", "fallback")
    is_ai = (source == "ai")

    # SYSTEM 1: Process User Memory ONLY if present and meaningful
    new_memory = None
    if is_ai and result.get("user_memory") and isinstance(result["user_memory"], dict):
        k = result["user_memory"].get("key")
        v = result["user_memory"].get("value")
        if k and v:
            mem_id = db.save_user_memory(req.session_id, k, v)
            if mem_id:
                new_memory = {"id": mem_id, "key": k, "value": v}
                if "name" in k.lower():
                    conn = db.get_db_connection()
                    conn.execute("UPDATE sessions SET user_name = ? WHERE session_id = ?", (v, req.session_id))
                    conn.commit()
                    conn.close()

    # SYSTEM 2: Process Earth Knowledge ONLY if genuine AI output
    new_knowledge = None
    if is_ai and result.get("earth_knowledge") and isinstance(result["earth_knowledge"], dict):
        topic = result["earth_knowledge"].get("topic")
        understanding = result["earth_knowledge"].get("alien_understanding")
        if topic and understanding:
            k_id = db.save_earth_knowledge(topic, understanding)
            if k_id:
                new_knowledge = {"id": k_id, "topic": topic, "alien_understanding": understanding}

    # SYSTEM 3: Process Alien Diary Entry ONLY if genuine AI output
    new_diary = None
    if is_ai and result.get("diary_entry") and isinstance(result["diary_entry"], dict):
        title = result["diary_entry"].get("title")
        category = result["diary_entry"].get("category", "Behaviour")
        obs = result["diary_entry"].get("observation")
        confusion = result["diary_entry"].get("confusion_level", 8)
        if title and obs:
            d_id = db.save_diary_entry(title, category, obs, confusion)
            if d_id:
                new_diary = {"id": d_id, "title": title, "category": category, "observation": obs, "confusion_level": confusion}

    # Save Jaadoo's reply to history tagged with source ("ai" or "fallback")
    db.save_message(req.session_id, "assistant", reply_text, source=source)

    return {
        "reply": reply_text,
        "reaction": reaction,
        "source": source,
        "user_memory": new_memory,
        "earth_knowledge": new_knowledge,
        "diary_entry": new_diary,
        "curiosity_question": result.get("curiosity_question"),
        "is_demo": result.get("is_demo", False),
        "status_notice": result.get("status_notice")
    }

# ==================== CONVERSATION HISTORY ====================

@app.get("/api/conversations")
def list_conversations(
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id"),
    visitor_id: Optional[str] = Query(None)
):
    """Return previous conversations. If visitor_id provided, returns only their own."""
    vid = _clean_str(x_visitor_id) or _clean_str(visitor_id)
    return db.get_all_conversations(visitor_id=vid, limit=50)

@app.get("/api/conversations/{session_id}/messages")
def get_conversation_history(
    session_id: str,
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id"),
    visitor_id: Optional[str] = Query(None)
):
    """Return full message history for a conversation in chronological order."""
    session = db.get_session(session_id)
    vid = _clean_str(x_visitor_id) or _clean_str(visitor_id)
    _verify_session_access(session, vid)
    return db.get_conversation_messages(session_id)

@app.patch("/api/conversations/{session_id}/title")
def rename_conversation(
    session_id: str,
    req: ConversationTitleRequest,
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id"),
    visitor_id: Optional[str] = Query(None)
):
    """Rename a conversation."""
    session = db.get_session(session_id)
    vid = _clean_str(x_visitor_id) or _clean_str(visitor_id)
    _verify_session_access(session, vid)

    success = db.update_conversation_title(session_id, req.title)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "updated", "session_id": session_id, "title": req.title}

@app.delete("/api/conversations/{session_id}")
def delete_conversation(
    session_id: str,
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id"),
    visitor_id: Optional[str] = Query(None)
):
    """Delete a conversation and all its messages/memories."""
    session = db.get_session(session_id)
    vid = _clean_str(x_visitor_id) or _clean_str(visitor_id)
    _verify_session_access(session, vid)

    success = db.delete_conversation(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"status": "deleted", "session_id": session_id}

# ==================== EXISTING ROUTES ====================

@app.get("/api/diary")
def get_diary():
    """System 3: Fetch all field observations recorded by Jaadoo."""
    return db.get_all_diary_entries()

@app.get("/api/earth-knowledge")
def get_earth_knowledge():
    """System 2: Fetch all general concepts decoded about Earth."""
    return db.get_all_earth_knowledge()

@app.get("/api/memories")
def get_memories(
    session_id: str = Query(...),
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id"),
    visitor_id: Optional[str] = Query(None)
):
    """System 1: Fetch meaningful memories saved about this user."""
    session = db.get_session(session_id)
    vid = _clean_str(x_visitor_id) or _clean_str(visitor_id)
    _verify_session_access(session, vid)
    return db.get_user_memories(session_id)

@app.delete("/api/memories/{memory_id}")
def delete_memory(
    memory_id: int,
    session_id: str = Query(...),
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id"),
    visitor_id: Optional[str] = Query(None)
):
    """Allows user to inspect and delete any remembered personal detail."""
    session = db.get_session(session_id)
    vid = _clean_str(x_visitor_id) or _clean_str(visitor_id)
    _verify_session_access(session, vid)

    success = db.delete_user_memory(memory_id, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found or unauthorized.")
    return {"status": "deleted", "memory_id": memory_id}

@app.get("/api/curiosity")
def get_curiosity():
    """Curiosity Mode: Trigger an unexpected alien question about human life."""
    question = agent.get_random_curiosity_question()
    return {"question": question, "alien_mood": "puzzled"}

@app.post("/api/reset")
def reset_session(
    req: MemoryDeleteRequest,
    x_visitor_id: Optional[str] = Header(None, alias="X-Visitor-Id")
):
    """Clear messages for the current session (resets conversation)."""
    session = db.get_session(req.session_id)
    vid = _clean_str(req.visitor_id) or _clean_str(x_visitor_id)
    if session:
        _verify_session_access(session, vid)
    db.clear_session_messages(req.session_id)
    agent.reset_curiosity_state(req.session_id)
    return {"status": "reset", "session_id": req.session_id}

@app.post("/api/config-key")
def configure_key(req: ConfigKeyRequest):
    """Allows dynamically configuring the GEMINI_API_KEY without restart."""
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key cannot be empty.")
    os.environ["GEMINI_API_KEY"] = key
    return {"status": "configured", "ai_available": agent.is_ai_available()}

@app.post("/api/backup")
def create_backup():
    """Online consistent backup of SQLite database."""
    target = db.backup_db()
    return {"status": "success", "backup_file": os.path.basename(target)}

# ==================== STATIC FILE SERVING ====================

app.mount("/css", StaticFiles(directory=os.path.join(BASE_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(BASE_DIR, "js")), name="js")
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "assets")), name="assets")

@app.get("/chat")
@app.get("/chat.html")
def serve_chat():
    return FileResponse(os.path.join(BASE_DIR, "chat.html"))

@app.get("/")
@app.get("/index.html")
def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))
