"""
ai/config.py
─────────────────────────────────────────────────────────────────────────────
Central configuration for the AI subsystem.

Detects which backend engine to use:
  PRIMARY  → Groq  (llama-3.3-70b-versatile / llama-3.1-8b-instant)
             Free tier: 30 RPM, 14 400 req/day  – effectively unlimited for demos
  FALLBACK → Google Gemini 1.5-flash  (multi-key round-robin, rate-limited)

Set GROQ_API_KEY in .env (free at console.groq.com) to enable Groq.
If absent, falls back to Gemini with the key rotation logic.
─────────────────────────────────────────────────────────────────────────────
"""
import os
import logging
from typing import List

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Groq ─────────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
USE_GROQ: bool = bool(GROQ_API_KEY)

# Models tried in order (primary → fallback).
# Only PRODUCTION models used — verified active as of April 2026.
# Source: https://console.groq.com/docs/models
GROQ_MODELS: List[str] = [
    "llama-3.3-70b-versatile",     # ✅ Production — primary (best quality)
    "openai/gpt-oss-120b",         # ✅ Production — 120B OpenAI OSS model
    "openai/gpt-oss-20b",          # ✅ Production — 20B fallback
    "llama-3.1-8b-instant",        # ✅ Production — fast/cheap final fallback
]

# ── Gemini ───────────────────────────────────────────────────────────────────
def _collect_gemini_keys() -> List[str]:
    """Collect all GEMINI_API_KEY / GEMINI_API_KEY_2 … from environment."""
    keys: List[str] = []
    primary = os.getenv("GEMINI_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    for i in range(2, 10):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if k:
            keys.append(k)
    return keys


ALL_KEYS: List[str] = _collect_gemini_keys()

# ── Startup log ───────────────────────────────────────────────────────────────
if USE_GROQ:
    log.info("✅ GROQ backend selected  (primary model: %s)", GROQ_MODELS[0])
elif ALL_KEYS:
    log.info("✅ Gemini backend selected (%d key(s))", len(ALL_KEYS))
else:
    log.error("❌ No AI API keys found! Set GROQ_API_KEY or GEMINI_API_KEY in .env")
