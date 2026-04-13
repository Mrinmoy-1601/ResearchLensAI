"""
ai/tools/summarizer.py
─────────────────────────────────────────────────────────────────────────────
Tool: Paper Summarization

Workflow
────────
1. Break paper into up to 8 chunks (larger papers trimmed for speed).
2. Summarize each chunk sequentially (to avoid rate-limit spikes).
3. Consolidate all chunk summaries into a single, structured paper summary.

This is the most expensive tool (~9 AI calls for an 8-chunk paper).
─────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import logging
from typing import List

from ai.router import call_ai
from ai.prompts import chunk_summary_prompt, paper_consolidation_prompt

# pdf_processor.Chunk is imported at call-time to avoid circular imports
# in type annotations only — kept here for IDE clarity.
from pdf_processor import Chunk

log = logging.getLogger(__name__)

MAX_CHUNKS = 8          # cap to keep latency reasonable
CHUNK_PAUSE_S = 1.0     # brief pause between chunk calls to respect RPM


async def _summarize_chunk(chunk: Chunk, chunk_num: int, total: int) -> str:
    """Summarize a single paper chunk."""
    log.info(
        "Summarizing chunk %d/%d (pages %s)", chunk_num, total, chunk.page_range
    )
    prompt = chunk_summary_prompt(chunk_num, total, chunk.page_range, chunk.text)
    return await call_ai(prompt, max_tokens=512)


async def summarize_paper(chunks: List[Chunk], title: str) -> str:
    """
    Generate a comprehensive summary of the paper.

    Args:
        chunks: List of text chunks from the PDF processor.
        title:  Detected paper title.

    Returns:
        Markdown-formatted summary string.
    """
    log.info("Starting summary for '%s' (%d chunks)", title, len(chunks))
    work_chunks = chunks[:MAX_CHUNKS]

    # ── Step 1: per-chunk summaries (sequential) ──────────────────────────
    chunk_summaries: List[str] = []
    for i, chunk in enumerate(work_chunks):
        summary = await _summarize_chunk(chunk, i + 1, len(work_chunks))
        chunk_summaries.append(summary)
        if i < len(work_chunks) - 1:
            await asyncio.sleep(CHUNK_PAUSE_S)

    # ── Step 2: filter out error responses ───────────────────────────────
    _error_prefixes = ("[AI error", "[QUOTA", "[GROQ", "[ERROR]")
    valid = [
        (i, s)
        for i, s in enumerate(chunk_summaries)
        if isinstance(s, str) and not any(s.startswith(p) for p in _error_prefixes)
    ]
    log.info("Got %d/%d valid chunk summaries", len(valid), len(work_chunks))

    if not valid:
        return "**Summary generation failed.** Check your API keys in `.env`."

    # ── Step 3: consolidate into full paper summary ───────────────────────
    combined = "\n\n".join(
        f"[Section {i + 1}, Pages {work_chunks[i].page_range}]:\n{s}"
        for i, s in valid
    )
    prompt = paper_consolidation_prompt(title, combined)
    log.info("Running consolidation call…")
    result = await call_ai(prompt, max_tokens=3000)
    log.info("Summary complete!")
    return result
