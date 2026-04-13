"""
session_store.py
In-memory session storage for uploaded paper chunks and derived results.
"""
import uuid
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from pdf_processor import Chunk, ExtractedPaper


@dataclass
class ChatMessage:
    role: str   # "user" | "assistant"
    content: str


@dataclass
class Session:
    session_id: str
    title: str
    full_text: str
    chunks: List[Chunk]
    summary: str = ""
    review: Optional[Dict[str, Any]] = None
    conferences: Optional[List[Dict]] = None
    similar_papers: Optional[List[Dict]] = None
    chat_history: List[ChatMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    num_pages: int = 0


# Global store — keyed by session_id
_sessions: Dict[str, Session] = {}
SESSION_TTL_SECONDS = 3600 * 4  # 4 hours


def create_session(paper: ExtractedPaper) -> Session:
    sid = str(uuid.uuid4())
    session = Session(
        session_id=sid,
        title=paper.title,
        full_text=paper.full_text,
        chunks=paper.chunks,
        num_pages=paper.num_pages,
    )
    _sessions[sid] = session
    _cleanup_old_sessions()
    return session


def get_session(session_id: str) -> Optional[Session]:
    return _sessions.get(session_id)


def _cleanup_old_sessions():
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s.created_at > SESSION_TTL_SECONDS]
    for sid in expired:
        del _sessions[sid]
