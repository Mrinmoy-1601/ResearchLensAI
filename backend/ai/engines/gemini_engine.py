"""
ai/engines/gemini_engine.py
─────────────────────────────────────────────────────────────────────────────
Async Gemini caller with:
  • Multi-key round-robin pool (_KeySlot)
  • Per-key RPM throttling (conservative 10 RPM)
  • Exponential back-off on 429 / RESOURCE_EXHAUSTED
  • Daily quota detection (quota_hit flag)
  • Semaphore limiting max concurrent calls (2)
  • Support for inline image content (base64 PNG)
─────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import logging
import random
import threading
import time
from typing import List, Optional

from ai.config import ALL_KEYS

log = logging.getLogger(__name__)

# ── Rate-limit constants ────────────────────────────────────────────────────
MAX_RPM_PER_KEY: int   = 10                         # conservative (free tier: 15 RPM)
MIN_INTERVAL:    float = 60.0 / MAX_RPM_PER_KEY     # seconds between calls per key
GEMINI_TIMEOUT:  int   = 90                          # seconds per call
_SEMAPHORE_SIZE: int   = 2                           # max concurrent Gemini calls


# ── _KeySlot ─────────────────────────────────────────────────────────────────

class _KeySlot:
    """
    Tracks rate-limit state for a single Gemini API key.

    Attributes:
        key:            Raw API key string.
        lock:           Per-slot asyncio lock (ensures only one caller
                        throttles at a time for this key).
        last_call:      monotonic timestamp of the last API call.
        quota_hit:      True if the daily quota has been exhausted.
        backoff_until:  monotonic timestamp — key is unavailable until then.
    """

    def __init__(self, key: str) -> None:
        self.key:           str            = key
        self.lock:          asyncio.Lock   = asyncio.Lock()
        self.last_call:     float          = 0.0
        self.quota_hit:     bool           = False
        self.backoff_until: float          = 0.0

    # ── Public helpers ───────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if the key can accept a new request right now."""
        return not self.quota_hit and time.monotonic() >= self.backoff_until

    async def throttle(self) -> None:
        """Sleep if needed to respect the per-key RPM limit."""
        now  = time.monotonic()
        wait = (self.last_call + MIN_INTERVAL) - now
        if wait > 0:
            log.debug("Gemini key …%s throttle: %.1fs", self.key[-6:], wait)
            await asyncio.sleep(wait)
        self.last_call = time.monotonic()

    def apply_backoff(self, attempt: int) -> None:
        """Apply exponential back-off after a rate-limit response."""
        backoff = 15 * (2 ** attempt) + random.uniform(0, 5)
        self.backoff_until = time.monotonic() + backoff
        log.warning(
            "Key …%s: rate-limited → backoff %.0fs", self.key[-6:], backoff
        )

    def mark_daily_quota_hit(self) -> None:
        """Mark the key as permanently unavailable (daily quota exhausted)."""
        self.quota_hit = True
        log.warning("Key …%s: DAILY quota exhausted", self.key[-6:])

    def reset_if_expired(self) -> None:
        """Re-enable the key if the backoff window has passed."""
        if self.backoff_until <= time.monotonic():
            self.backoff_until = 0.0
            # Do NOT reset quota_hit — that only resets at midnight


# ── Module-level pool ─────────────────────────────────────────────────────────

_key_slots: List[_KeySlot] = [_KeySlot(k) for k in ALL_KEYS]
_key_index:  int            = 0
_key_lock:   asyncio.Lock   = asyncio.Lock()

# Thread lock for the global genai.configure() call (not async-safe)
_gemini_configure_lock: threading.Lock = threading.Lock()

_semaphore: asyncio.Semaphore = asyncio.Semaphore(_SEMAPHORE_SIZE)


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _pick_key() -> Optional[_KeySlot]:
    """Return the next available key slot using round-robin, or None."""
    global _key_index
    async with _key_lock:
        for _ in range(len(_key_slots)):
            slot = _key_slots[_key_index % len(_key_slots)]
            _key_index += 1
            if slot.available:
                return slot
    return None


def _build_content_parts(prompt: str, image_b64_list: Optional[List[str]]):
    """Build the content parts list for a Gemini generate_content call."""
    if not image_b64_list:
        return prompt  # plain text — faster path
    parts = [prompt]
    for b64 in image_b64_list[:2]:  # cap at 2 images to limit token usage
        parts.append(
            {"inline_data": {"mime_type": "image/png", "data": b64}}
        )
    return parts


# ── Public API ────────────────────────────────────────────────────────────────

async def call_gemini(
    prompt: str,
    image_b64_list: Optional[List[str]] = None,
    model_name: str = "gemini-1.5-flash",
) -> str:
    """
    Call Google Gemini asynchronously using the managed key-slot pool.

    Each attempt:
      1. Picks an available key (round-robin).
      2. Throttles to respect RPM limit.
      3. Runs the sync SDK call in a thread-pool executor.
      4. Applies back-off on 429 / RESOURCE_EXHAUSTED responses.

    Args:
        prompt:         Prompt text.
        image_b64_list: Optional list of base64-encoded PNG images.
        model_name:     Gemini model identifier.

    Returns:
        Generated text, or a descriptive error string starting with '['.
    """
    import google.generativeai as genai  # lazy import

    async with _semaphore:
        for attempt in range(5):
            slot = await _pick_key()

            # ── All keys exhausted — wait and try resetting expired ones ──
            if slot is None:
                wait_s = 15 * (attempt + 1)
                log.warning(
                    "All Gemini keys exhausted (attempt %d). Waiting %ds…",
                    attempt, wait_s,
                )
                await asyncio.sleep(wait_s)
                for s in _key_slots:
                    s.reset_if_expired()
                continue

            await slot.throttle()

            # ── Sync SDK call —wrapped in executor so the event-loop stays free ──
            content_parts = _build_content_parts(prompt, image_b64_list)

            def _sync_call(key: str = slot.key) -> str:
                with _gemini_configure_lock:
                    genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name)
                return model.generate_content(
                    content_parts,
                    request_options={"timeout": GEMINI_TIMEOUT},
                ).text

            loop = asyncio.get_event_loop()
            try:
                result: str = await asyncio.wait_for(
                    loop.run_in_executor(None, _sync_call),
                    timeout=GEMINI_TIMEOUT + 10,
                )
                log.info(
                    "Gemini OK [key …%s] (len=%d)", slot.key[-6:], len(result)
                )
                return result

            except asyncio.TimeoutError:
                log.error(
                    "Gemini TIMEOUT […%s] attempt %d", slot.key[-6:], attempt
                )
                await asyncio.sleep(5)
                continue

            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                if (
                    "429" in err
                    or "quota" in err.lower()
                    or "RESOURCE_EXHAUSTED" in err
                ):
                    if "day" in err.lower() or "daily" in err.lower():
                        slot.mark_daily_quota_hit()
                    else:
                        slot.apply_backoff(attempt)
                    continue
                log.error("Gemini ERROR […%s]: %s", slot.key[-6:], exc)
                return f"[AI error: {exc}]"

    return (
        "[QUOTA_EXCEEDED] All Gemini API keys have reached their rate limit. "
        "Please wait 1–2 minutes and retry, or add a free Groq key "
        "(GROQ_API_KEY) from https://console.groq.com for unlimited free access."
    )
