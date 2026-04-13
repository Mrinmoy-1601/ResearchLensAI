"""
ai/tools/reviewer.py
─────────────────────────────────────────────────────────────────────────────
Tool: Academic Peer Review

Generates a structured peer review for the uploaded paper, including:
  - Verdict (Accept / Minor Revision / Major Revision / Reject)
  - Dimension scores (Novelty, Methodology, Clarity, Results, Overall)
  - Strengths, Weaknesses, Improvement Steps, Recommendation Details

The full_text is sampled to the first 12 000 characters to stay within
context limits while covering the abstract, introduction, and methodology.
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Any, Dict

from ai.router import call_ai
from ai.prompts import peer_review_prompt

log = logging.getLogger(__name__)

TEXT_SAMPLE_CHARS = 12_000   # characters fed to the reviewer


async def review_paper(full_text: str, title: str) -> Dict[str, Any]:
    """
    Generate a peer review for the paper.

    Args:
        full_text: Full extracted paper text.
        title:     Paper title.

    Returns:
        Dict with keys:
          - raw_review (str): Full markdown review text.
          - title      (str): Paper title (echoed for the frontend).
    """
    text_sample = full_text[:TEXT_SAMPLE_CHARS]
    prompt = peer_review_prompt(title, text_sample)

    log.info("Generating peer review for '%s'", title)
    raw = await call_ai(prompt, max_tokens=3000)
    log.info("Peer review complete (len=%d)", len(raw))

    return {"raw_review": raw, "title": title}
