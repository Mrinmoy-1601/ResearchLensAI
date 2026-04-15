"""
ai/tools/chatbot.py
─────────────────────────────────────────────────────────────────────────────
Tool: RAG-powered Chatbot

Retrieval strategy: keyword overlap scoring.
  • Tokenise the question (words > 3 chars).
  • Score each chunk by counting matching words.
  • Return the top-K chunks as context.

The answer prompt includes paper summary, retrieved context, and the last
6 conversation turns so the model can maintain coherence.
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Any, Dict, List

from ai.router import call_ai
from ai.prompts import rag_answer_prompt
from pdf_processor import Chunk
from session_store import ChatMessage

log = logging.getLogger(__name__)

RAG_TOP_K = 4          # number of chunks to retrieve per question
HISTORY_TURNS = 6      # number of past message pairs to include


def _retrieve_relevant_chunks(
    question: str, chunks: List[Chunk], top_k: int = RAG_TOP_K
) -> List[Chunk]:
    """
    Retrieve the most relevant chunks using keyword overlap scoring.

    Args:
        question: User question string.
        chunks:   All paper chunks.
        top_k:    Maximum number of chunks to return.

    Returns:
        Ordered list of most relevant chunks (best first).
    """
    q_words = {w for w in question.lower().split() if len(w) > 3}
    scored = []
    for chunk in chunks:
        text_lower = chunk.text.lower()
        score = sum(1 for w in q_words if w in text_lower)
        scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    # Always return at least something even if no keyword matches
    retrieved = [c for _, c in scored[:top_k]]
    return retrieved or chunks[:top_k]


async def answer_question(
    question: str,
    chunks: List[Chunk],
    history: List[ChatMessage],
    title: str,
    summary: str,
) -> Dict[str, Any]:
    """
    Answer a user question using RAG over the paper chunks.

    Args:
        question: The user's question.
        chunks:   All paper chunks (for retrieval).
        history:  Full conversation history.
        title:    Paper title.
        summary:  Pre-generated paper summary.

    Returns:
        Dict with keys:
          - reply     (str): Markdown-formatted answer.
          - page_refs (list[str]): Page ranges of retrieved chunks.
    """
    relevant = _retrieve_relevant_chunks(question, chunks)
    context_parts = [f"[Pages {c.page_range}]\n{c.text}" for c in relevant]
    context = "\n\n---\n\n".join(context_parts)

    history_text = "\n".join(
        f"{m.role.upper()}: {m.content}" for m in history[-HISTORY_TURNS:]
    )

    prompt = rag_answer_prompt(title, summary, context, history_text, question)
    log.info("RAG answer | question=%r | retrieved_chunks=%d", question[:60], len(relevant))

    answer = await call_ai(prompt, max_tokens=2048)
    
    # Process the raw text answer into a structured JSON file via the new agent
    from ai.tools.json_filter import process_answer_to_json
    import asyncio
    # Run in background to avoid blocking the response, or run synchronously. We run async.
    asyncio.create_task(process_answer_to_json(answer, output_file="answer.json"))

    page_refs = list({c.page_range for c in relevant})
    return {"reply": answer, "page_refs": page_refs}
