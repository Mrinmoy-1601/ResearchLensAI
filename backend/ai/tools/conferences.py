"""
ai/tools/conferences.py
─────────────────────────────────────────────────────────────────────────────
Tool: Conference & Journal Suggestions

Given a paper title, summary, and web search results, recommend the top 6
most relevant publication venues.
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Any, Dict, List

from ai.router import call_ai
from ai.prompts import conference_suggestion_prompt

log = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 15   # cap to stay within prompt size


async def generate_conference_suggestions(
    title: str,
    abstract: str,
    search_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Generate venue suggestions for the paper.

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
    prompt = conference_suggestion_prompt(title, abstract, search_text)

    log.info("Generating conference suggestions for '%s'", title)
    raw = await call_ai(prompt, max_tokens=2000)
    log.info("Conference suggestions complete (len=%d)", len(raw))

    return [{"raw": raw}]
