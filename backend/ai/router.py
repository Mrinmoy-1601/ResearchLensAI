"""
ai/router.py
─────────────────────────────────────────────────────────────────────────────
Unified AI dispatcher.

Decision logic
──────────────
1. Groq active + text-only           → Groq text chain
2. Groq active + images provided     → Groq vision chain (Llama-4-Scout etc.)
3. Only Gemini keys available        → Gemini (supports both text and images)
4. Neither configured                → descriptive error string
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from typing import List, Optional

from ai.config import USE_GROQ, ALL_KEYS
from ai.engines.groq_engine import call_groq
from ai.engines.gemini_engine import call_gemini

log = logging.getLogger(__name__)


async def call_ai(
    prompt: str,
    image_b64_list: Optional[List[str]] = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Route a prompt to the best available AI backend.

    Args:
        prompt:         The prompt to send to the model.
        image_b64_list: Optional base64 PNG images.
        max_tokens:     Token budget for the response.
        temperature:    Sampling temperature.
        system_prompt:  Optional system-role message (text calls only).

    Returns:
        Generated text, or a descriptive error string starting with '['.
    """
    if USE_GROQ:
        # Groq handles both text and vision — pass images directly
        log.debug("Routing → Groq (images=%s)", bool(image_b64_list))
        return await call_groq(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
            image_b64_list=image_b64_list,
        )

    if ALL_KEYS:
        log.debug("Routing → Gemini (images=%s)", bool(image_b64_list))
        return await call_gemini(prompt, image_b64_list)

    return (
        "[ERROR] No AI backend configured. "
        "Set GROQ_API_KEY or GEMINI_API_KEY in your .env file."
    )
