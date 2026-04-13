"""
ai/tools/image_enricher.py
─────────────────────────────────────────────────────────────────────────────
Tool: Image & Table Description via Groq Vision

Two public functions:
  • describe_image  — sends a base64 PNG to Groq vision (Llama-4-Scout) and
                      returns a detailed description
  • enrich_chunks_with_image_descriptions — background task that:
      1. Describes images in chunks via Groq vision
      2. Describes structured tables using Groq text (no vision needed)
      Appends all descriptions to chunk.text for richer RAG context.
─────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import logging
from typing import List

from ai.router import call_ai
from pdf_processor import Chunk

log = logging.getLogger(__name__)

MAX_IMAGES_TOTAL   = 6        # images to enrich across all chunks
IMAGE_CALL_PAUSE_S = 2.0      # pause between successive vision calls
TABLE_CALL_PAUSE_S = 1.0      # pause between table description calls
_ERROR_PREFIXES    = ("[AI error", "[QUOTA", "[GROQ", "[ERROR]", "[Image")


# ── Image description ─────────────────────────────────────────────────────────

async def describe_image(b64: str) -> str:
    """
    Generate a detailed description of a base64-encoded PNG image
    using Groq vision (Llama-4-Scout / llama-3.2-vision).

    The prompt is research-paper–specific to get useful output.
    """
    prompt = (
        "You are a research paper analyst examining a figure from an academic paper.\n\n"
        "Describe this image in detail:\n"
        "1. What TYPE of figure is this? (graph, chart, diagram, photograph, etc.)\n"
        "2. What DATA or INFORMATION does it show? (axes labels, legend, key values)\n"
        "3. What is the MAIN TAKEAWAY or finding shown in this figure?\n"
        "4. Are there any NOTABLE PATTERNS, trends, or comparisons visible?\n\n"
        "Be specific and concise. 3-5 sentences. Focus on quantitative details if visible."
    )
    return await call_ai(prompt, image_b64_list=[b64], max_tokens=400, temperature=0.2)


# ── Table description ─────────────────────────────────────────────────────────

async def describe_table(table_markdown: str, page_num: int) -> str:
    """
    Generate a natural-language description of a markdown table using
    Groq text models (no vision needed — the table is already extracted as text).
    """
    prompt = (
        f"You are analyzing a table from page {page_num} of a research paper.\n\n"
        f"TABLE CONTENT (Markdown):\n{table_markdown[:2000]}\n\n"
        "Provide a brief but informative summary of this table:\n"
        "1. What does this table show/compare?\n"
        "2. What are the column categories?\n"
        "3. What are the KEY findings or notable values?\n"
        "4. How does this table contribute to the paper's argument?\n\n"
        "Keep it under 4 sentences. Be factual and specific."
    )
    return await call_ai(prompt, max_tokens=300, temperature=0.2)


# ── Main enrichment task ──────────────────────────────────────────────────────

async def enrich_chunks_with_image_descriptions(chunks: List[Chunk]) -> None:
    """
    Background task: describe images AND tables in chunks, then augment chunk.text.

    This runs after upload so it doesn't block the summary response.
    Both image descriptions and table summaries are appended to chunk.text,
    making the RAG retrieval richer.

    Args:
        chunks: All paper chunks (modified in-place).
    """
    # ── Collect image tasks ───────────────────────────────────────────────
    image_tasks: List[tuple] = []
    for chunk in chunks:
        images = getattr(chunk, "_images_b64", [])
        for b64 in images[:1]:   # max 1 image per chunk
            if len(image_tasks) >= MAX_IMAGES_TOTAL:
                break
            image_tasks.append((chunk, b64))

    # ── Process images ────────────────────────────────────────────────────
    if image_tasks:
        log.info("Image enrichment: processing %d image(s) via Groq vision…", len(image_tasks))
        for i, (chunk, b64) in enumerate(image_tasks):
            desc = await describe_image(b64)
            if isinstance(desc, str) and not any(desc.startswith(p) for p in _ERROR_PREFIXES):
                chunk.image_descriptions.append(desc)
                chunk.text += f"\n\n[FIGURE DESCRIPTION (Page {chunk.page_range}): {desc}]"
                log.debug("Image %d/%d described (%d chars)", i + 1, len(image_tasks), len(desc))
            else:
                log.warning("Image %d/%d failed: %s", i + 1, len(image_tasks), str(desc)[:80])
            if i < len(image_tasks) - 1:
                await asyncio.sleep(IMAGE_CALL_PAUSE_S)
        log.info("Image enrichment complete.")
    else:
        log.info("No images found to enrich.")

    # ── Process tables ────────────────────────────────────────────────────
    table_tasks: List[tuple] = []
    for chunk in chunks:
        for tbl in getattr(chunk, "tables", [])[:2]:  # max 2 tables per chunk
            if len(table_tasks) >= 8:
                break
            table_tasks.append((chunk, tbl))

    if table_tasks:
        log.info("Table enrichment: describing %d table(s) via Groq…", len(table_tasks))
        for i, (chunk, tbl) in enumerate(table_tasks):
            desc = await describe_table(tbl.markdown, tbl.page_num)
            if isinstance(desc, str) and not any(desc.startswith(p) for p in _ERROR_PREFIXES):
                chunk.text += f"\n\n[TABLE SUMMARY (Page {tbl.page_num}): {desc}]"
                log.debug("Table %d/%d described", i + 1, len(table_tasks))
            if i < len(table_tasks) - 1:
                await asyncio.sleep(TABLE_CALL_PAUSE_S)
        log.info("Table enrichment complete.")
    else:
        log.info("No structured tables found to describe.")
