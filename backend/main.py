"""
main.py — FastAPI application for ResearchLens AI
─────────────────────────────────────────────────────────────────────────────
Route map
  GET  /              → serve frontend index.html
  GET  /static/*      → static frontend assets
  GET  /health        → liveness check
  GET  /keys          → AI engine / key-pool status
  POST /upload        → upload PDF → returns session_id + summary
  POST /chat          → RAG chatbot turn
  GET  /review/{id}   → peer review (cached per session)
  GET  /conferences/{id} → publication venue suggestions (cached)
  GET  /similar/{id}  → similar paper discovery (cached)
─────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import logging
import os
import time

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [API] %(message)s")
log = logging.getLogger(__name__)

# ── Domain imports ────────────────────────────────────────────────────────────
from pdf_processor import extract_paper
from session_store import ChatMessage, create_session, get_session
import ai                                    # new modular AI package
import search_service as search
from auth import router as auth_router       # authentication

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="ResearchLens AI", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

# ── Static frontend ──────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)


@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ── Explicit static file routes (guaranteed correct MIME types) ───────────────
@app.get("/static/style.css", include_in_schema=False)
async def serve_css():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "style.css"),
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/static/app.js", include_in_schema=False)
async def serve_js():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "app.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "ResearchLens AI", "version": "2.0.0"}


# ── AI engine / key-pool status ───────────────────────────────────────────────
@app.get("/keys")
async def keys_status():
    now = time.monotonic()

    if ai.USE_GROQ:
        return {
            "engine": "groq",
            "groq_key_set": bool(ai.GROQ_API_KEY),
            "groq_models": ai.GROQ_MODELS,
            "gemini_fallback_keys": len(ai.ALL_KEYS),
        }

    return {
        "engine": "gemini",
        "total_keys": len(ai.ALL_KEYS),
        "keys": [
            {
                "index": i + 1,
                "suffix": f"…{s.key[-6:]}",
                "available": s.available,
                "quota_daily_hit": s.quota_hit,
                "backoff_remaining_s": max(0, round(s.backoff_until - now, 1)),
            }
            for i, s in enumerate(ai._key_slots)
        ],
    }


# ── 1. Upload PDF ─────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    log.info("Received PDF: %s (%.1f KB)", file.filename, len(pdf_bytes) / 1024)

    # Extract paper structure
    try:
        paper = extract_paper(pdf_bytes)
        log.info(
            "Extracted paper: %d pages, %d chunks", paper.num_pages, len(paper.chunks)
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}")

    # Create session
    session = create_session(paper)

    # Image enrichment runs in the background — does NOT block the summary
    asyncio.create_task(
        ai.enrich_chunks_with_image_descriptions(session.chunks)
    )

    # Generate paper summary (main work)
    log.info("Generating summary for session %s…", session.session_id)
    try:
        summary = await ai.summarize_paper(session.chunks, session.title)
    except Exception as exc:
        log.error("Summary failed: %s", exc)
        summary = f"Summary generation failed: {exc}"

    session.summary = summary
    # Store keyword snippet for later search calls
    session._keywords = " ".join(session.title.split()[:6])  # type: ignore[attr-defined]

    log.info("Upload complete — session %s", session.session_id)
    return {
        "session_id": session.session_id,
        "title": session.title,
        "num_pages": session.num_pages,
        "num_chunks": len(session.chunks),
        "summary": summary,
        "has_images": paper.has_images,
        "has_tables": paper.has_tables,
    }


# ── 2. Chat ───────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: str
    message: str


@app.post("/chat")
async def chat(req: ChatRequest):
    session = get_session(req.session_id)
    if not session:
        raise HTTPException(
            status_code=404, detail="Session not found. Please re-upload the paper."
        )
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    session.chat_history.append(ChatMessage(role="user", content=req.message))

    result = await ai.answer_question(
        question=req.message,
        chunks=session.chunks,
        history=session.chat_history,
        title=session.title,
        summary=session.summary,
    )

    session.chat_history.append(
        ChatMessage(role="assistant", content=result["reply"])
    )

    return {"reply": result["reply"], "page_refs": result.get("page_refs", [])}


# ── 3. Review ─────────────────────────────────────────────────────────────────
@app.get("/review/{session_id}")
async def get_review(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.review:
        session.review = await ai.review_paper(session.full_text, session.title)

    return session.review


# ── 4. Conferences ────────────────────────────────────────────────────────────
@app.get("/conferences/{session_id}")
async def get_conferences(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.conferences:
        keywords = getattr(session, "_keywords", session.title[:50])
        search_results = await search.search_conferences(session.title, keywords)
        session.conferences = await ai.generate_conference_suggestions(
            session.title, session.summary, search_results
        )

    return {"conferences": session.conferences}


# ── 5. Similar papers ─────────────────────────────────────────────────────────
@app.get("/similar/{session_id}")
async def get_similar_papers(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    if not session.similar_papers:
        keywords = getattr(session, "_keywords", session.title[:50])
        search_results = await search.search_similar_papers(session.title, keywords)
        session.similar_papers = await ai.generate_similar_papers(
            session.title, session.summary, search_results
        )

    return {"similar_papers": session.similar_papers}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        timeout_keep_alive=120,
    )
