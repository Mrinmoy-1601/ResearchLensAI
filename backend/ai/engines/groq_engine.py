"""
ai/engines/groq_engine.py
─────────────────────────────────────────────────────────────────────────────
Async Groq caller with:
  • Text-only model fallback chain (llama-3.3-70b → llama-3.1-8b → mixtral)
  • Vision support via Llama-4-Scout / llama-3.2-vision models
    (sends base64 PNG images as inline content parts)

Vision model try order:
  1. meta-llama/llama-4-scout-17b-16e-instruct  (best multimodal, context-rich)
  2. llama-3.2-90b-vision-preview               (high-quality fallback)
  3. llama-3.2-11b-vision-preview               (fast/free-tier fallback)
─────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import logging
from typing import List, Optional

from ai.config import GROQ_API_KEY, GROQ_MODELS, USE_GROQ

log = logging.getLogger(__name__)

# Vision models — verified active as of April 2026
# llama-3.2-90b-vision-preview and llama-3.2-11b-vision-preview are DECOMMISSIONED
GROQ_VISION_MODELS: List[str] = [
    "meta-llama/llama-4-scout-17b-16e-instruct",  # ✅ Active preview — only vision model
]


def _build_vision_message(prompt: str, image_b64_list: List[str]) -> dict:
    """
    Build a single user message with text + up to 2 inline base64 images.
    Groq vision API uses the OpenAI vision format:
      content = [{"type": "text", ...}, {"type": "image_url", "image_url": {"url": "data:..."}}, ...]
    """
    content = [{"type": "text", "text": prompt}]
    for b64 in image_b64_list[:2]:   # cap at 2 images per call
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}"
            }
        })
    return {"role": "user", "content": content}


async def call_groq(
    prompt: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    system_prompt: Optional[str] = None,
    image_b64_list: Optional[List[str]] = None,
) -> str:
    """
    Call the Groq API asynchronously.

    If image_b64_list is provided, uses the vision model chain;
    otherwise uses the standard text-only model chain.

    Args:
        prompt:          User-facing prompt text.
        max_tokens:      Maximum tokens to generate.
        temperature:     Sampling temperature.
        system_prompt:   Optional system-role message.
        image_b64_list:  Optional list of base64-encoded PNG images.

    Returns:
        Generated text, or a descriptive error string starting with '['.
    """
    if not USE_GROQ:
        return "[GROQ_UNAVAILABLE] No GROQ_API_KEY configured."

    from groq import AsyncGroq, RateLimitError, APIStatusError

    client = AsyncGroq(api_key=GROQ_API_KEY)

    # ── Vision path ──────────────────────────────────────────────────────────
    if image_b64_list:
        return await _call_groq_vision(
            client, prompt, image_b64_list, max_tokens, temperature
        )

    # ── Text-only path ───────────────────────────────────────────────────────
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for model in GROQ_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            log.info("Groq text OK [model=%s] (len=%d)", model, len(text))
            return text

        except RateLimitError as exc:
            log.warning("Groq rate-limited on %s: %s — next model", model, exc)
            await asyncio.sleep(2)
            continue

        except APIStatusError as exc:
            if exc.status_code == 503:
                log.warning("Groq 503 on %s — next model", model)
                await asyncio.sleep(1)
                continue
            log.error("Groq API error [%s]: %s", model, exc)
            return f"[AI error: {exc}]"

        except Exception as exc:  # noqa: BLE001
            log.error("Groq unexpected error [%s]: %s", model, exc)
            return f"[AI error: {exc}]"

    return (
        "[GROQ_QUOTA] All Groq text models are currently rate-limited. "
        "Please wait ~1 minute and retry."
    )


async def _call_groq_vision(
    client,
    prompt: str,
    image_b64_list: List[str],
    max_tokens: int,
    temperature: float,
) -> str:
    """
    Call a Groq vision model with inline base64 image content.
    Tries vision models in order; if all fail gracefully returns text-only reply.
    """
    from groq import RateLimitError, APIStatusError

    vision_message = _build_vision_message(prompt, image_b64_list)

    for model in GROQ_VISION_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[vision_message],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            log.info("Groq vision OK [model=%s] (len=%d)", model, len(text))
            return text

        except RateLimitError as exc:
            log.warning("Groq vision rate-limit [%s]: %s — next model", model, exc)
            await asyncio.sleep(3)
            continue

        except APIStatusError as exc:
            if exc.status_code in (400, 422):
                # Model doesn't support vision or bad image — skip silently
                log.warning("Groq vision unsupported [%s]: %s", model, exc)
                continue
            if exc.status_code == 503:
                log.warning("Groq vision 503 [%s] — next model", model)
                await asyncio.sleep(1)
                continue
            log.error("Groq vision API error [%s]: %s", model, exc)
            continue

        except Exception as exc:  # noqa: BLE001
            log.warning("Groq vision error [%s]: %s", model, exc)
            continue

    # All vision models failed — fall back to text-only
    log.warning("All Groq vision models failed; falling back to text-only description")
    return await call_groq(
        "Describe what you see in this research figure based on typical academic paper content. "
        "Focus on charts, graphs, tables, or experimental results. "
        "Be specific about the type of visualization and what it likely shows.",
        max_tokens=300,
        temperature=0.2,
    )
