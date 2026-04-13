"""
ai/tools/similar_papers.py
─────────────────────────────────────────────────────────────────────────────
Tool: Similar Paper Discovery

Given a paper title, summary, and web search results, identify the 7 most
closely related papers and explain the relationship to each.
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Any, Dict, List

from ai.router import call_ai
from ai.prompts import similar_papers_prompt

log = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 20   # cap for prompt size


async def generate_similar_papers(
    title: str,
    abstract: str,
    search_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Discover and describe similar research papers.

    Args:
        title:          Paper title.
        abstract:       Paper summary / abstract text.
        search_results: List of {title, url, snippet} dicts from search_service.

    Returns:
        List with a single dict ``{"raw": <markdown text>}``.
        The frontend renders the raw markdown directly.
    """
    search_text = "\n".join(
        f"- {r.get('title', '')}: {r.get('url', '')}"
        for r in search_results[:MAX_SEARCH_RESULTS]
    )
    prompt = similar_papers_prompt(title, abstract, search_text)

    log.info("Generating similar papers for '%s'", title)
    raw = await call_ai(prompt, max_tokens=2000)
    log.info("Similar papers complete (len=%d)", len(raw))

    return [{"raw": raw}]
