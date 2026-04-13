"""
ai/__init__.py
Public API for the ai package.
Import everything AI-related from this single entry point.
"""
from ai.tools.summarizer import summarize_paper
from ai.tools.chatbot import answer_question
from ai.tools.reviewer import review_paper
from ai.tools.conferences import generate_conference_suggestions
from ai.tools.similar_papers import generate_similar_papers
from ai.tools.image_enricher import enrich_chunks_with_image_descriptions, describe_image
from ai.config import USE_GROQ, GROQ_API_KEY, GROQ_MODELS, ALL_KEYS
from ai.engines.gemini_engine import _key_slots  # for /keys endpoint

__all__ = [
    "summarize_paper",
    "answer_question",
    "review_paper",
    "generate_conference_suggestions",
    "generate_similar_papers",
    "enrich_chunks_with_image_descriptions",
    "describe_image",
    "USE_GROQ",
    "GROQ_API_KEY",
    "GROQ_MODELS",
    "ALL_KEYS",
    "_key_slots",
]
