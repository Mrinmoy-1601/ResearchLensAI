"""
ai/prompts/__init__.py
"""
from ai.prompts.templates import (
    image_description_prompt,
    chunk_summary_prompt,
    paper_consolidation_prompt,
    rag_answer_prompt,
    peer_review_prompt,
    conference_suggestion_prompt,
    similar_papers_prompt,
)

__all__ = [
    "image_description_prompt",
    "chunk_summary_prompt",
    "paper_consolidation_prompt",
    "rag_answer_prompt",
    "peer_review_prompt",
    "conference_suggestion_prompt",
    "similar_papers_prompt",
]
