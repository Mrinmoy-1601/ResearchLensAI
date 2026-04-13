"""
ai_service.py
─────────────────────────────────────────────────────────────────────────────
Dual-engine AI backend:
  PRIMARY  → Groq  (llama-3.3-70b-versatile / llama-3.1-8b-instant)
             Free tier: 30 RPM, 14 400 req/day  – effectively unlimited for demos
  FALLBACK → Google Gemini 1.5-flash  (multi-key round-robin, rate-limited)

Set GROQ_API_KEY in .env (free at console.groq.com) to enable Groq.
If absent, falls back to Gemini with the existing key rotation logic (fixed).
─────────────────────────────────────────────────────────────────────────────
"""
import asyncio
import os
import time
import base64
import logging
import random
import threading
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

from pdf_processor import Chunk
from session_store import ChatMessage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [AI] %(message)s")
log = logging.getLogger(__name__)

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE SELECTION
# ═══════════════════════════════════════════════════════════════════════════════

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
USE_GROQ = bool(GROQ_API_KEY)

# Groq models (tried in order)
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

# ─── Collect all Gemini API keys from .env ────────────────────────────────────
def _collect_gemini_keys() -> List[str]:
    keys = []
    k = os.getenv("GEMINI_API_KEY", "").strip()
    if k:
        keys.append(k)
    for i in range(2, 10):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if k:
            keys.append(k)
    return keys

ALL_KEYS: List[str] = _collect_gemini_keys()

if USE_GROQ:
    log.info("✅ GROQ backend selected  (model: %s)", GROQ_MODELS[0])
elif ALL_KEYS:
    log.info("✅ Gemini backend selected (%d key(s))", len(ALL_KEYS))
else:
    log.error("❌ No AI API keys found!  Set GROQ_API_KEY or GEMINI_API_KEY in .env")


# ═══════════════════════════════════════════════════════════════════════════════
# GROQ BACKEND
# ═══════════════════════════════════════════════════════════════════════════════

async def _call_groq(prompt: str, max_tokens: int = 2048) -> str:
    """Call Groq async API — tries each model in fallback order."""
    if not USE_GROQ:
        return "[GROQ_UNAVAILABLE] No GROQ_API_KEY set."

    from groq import AsyncGroq, RateLimitError, APIStatusError

    client = AsyncGroq(api_key=GROQ_API_KEY)

    for model in GROQ_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            text = response.choices[0].message.content or ""
            log.info("Groq OK [model=%s] (len=%d)", model, len(text))
            return text

        except RateLimitError as e:
            log.warning("Groq rate limit on %s: %s — trying next model", model, e)
            await asyncio.sleep(2)
            continue

        except APIStatusError as e:
            if e.status_code == 503:
                log.warning("Groq 503 on %s — trying next model", model)
                await asyncio.sleep(1)
                continue
            log.error("Groq API error [%s]: %s", model, e)
            return f"[AI error: {e}]"

        except Exception as e:
            log.error("Groq unexpected error [%s]: %s", model, e)
            return f"[AI error: {e}]"

    return "[GROQ_QUOTA] All Groq models rate-limited. Please wait ~1 minute."


# ═══════════════════════════════════════════════════════════════════════════════
# GEMINI BACKEND  (fixed: per-call configure inside a threading lock)
# ═══════════════════════════════════════════════════════════════════════════════

MAX_RPM_PER_KEY = 10          # conservative limit (free tier: 15 RPM)
MIN_INTERVAL    = 60.0 / MAX_RPM_PER_KEY   # 6 s between calls per key

class _KeySlot:
    def __init__(self, key: str):
        self.key          = key
        self.lock         = asyncio.Lock()
        self.last_call    = 0.0
        self.quota_hit    = False
        self.backoff_until = 0.0

    @property
    def available(self) -> bool:
        return not self.quota_hit and time.monotonic() >= self.backoff_until

    async def throttle(self):
        now  = time.monotonic()
        wait = (self.last_call + MIN_INTERVAL) - now
        if wait > 0:
            log.debug("Gemini key throttle: %.1fs", wait)
            await asyncio.sleep(wait)
        self.last_call = time.monotonic()


_key_slots: List[_KeySlot] = [_KeySlot(k) for k in ALL_KEYS]
_key_index  = 0
_key_lock   = asyncio.Lock()
_gemini_configure_lock = threading.Lock()   # guard global genai.configure()

_semaphore = asyncio.Semaphore(2)   # max 2 concurrent Gemini calls
GEMINI_TIMEOUT = 90


async def _pick_key() -> Optional[_KeySlot]:
    global _key_index
    async with _key_lock:
        for _ in range(len(_key_slots)):
            slot = _key_slots[_key_index % len(_key_slots)]
            _key_index += 1
            if slot.available:
                return slot
    return None


async def _call_gemini(
    prompt: str,
    image_b64_list: Optional[List[str]] = None,
    model_name: str = "gemini-1.5-flash",
) -> str:
    """Calls Gemini with per-call key configure (thread-safe)."""
    import google.generativeai as genai

    async with _semaphore:
        for attempt in range(5):
            slot = await _pick_key()
            if slot is None:
                wait = 15 * (attempt + 1)
                log.warning("All Gemini keys exhausted. Waiting %ds…", wait)
                await asyncio.sleep(wait)
                now = time.monotonic()
                for s in _key_slots:
                    if s.backoff_until <= now:
                        s.backoff_until = 0.0
                        s.quota_hit = False
                continue

            await slot.throttle()

            # ── sync call wrapped in executor ──────────────────────────────
            def _sync_call(key=slot.key):
                # Each executor thread must configure its own key before calling
                with _gemini_configure_lock:
                    genai.configure(api_key=key)
                model = genai.GenerativeModel(model_name)
                if image_b64_list:
                    parts = [prompt]
                    for b64 in image_b64_list[:2]:
                        parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})
                    return model.generate_content(
                        parts, request_options={"timeout": GEMINI_TIMEOUT}
                    ).text
                return model.generate_content(
                    prompt, request_options={"timeout": GEMINI_TIMEOUT}
                ).text

            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, _sync_call),
                    timeout=GEMINI_TIMEOUT + 10,
                )
                log.info("Gemini OK [key …%s] (len=%d)", slot.key[-6:], len(result))
                return result

            except asyncio.TimeoutError:
                log.error("Gemini TIMEOUT [%s] attempt %d", slot.key[-6:], attempt)
                await asyncio.sleep(5)
                continue

            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                    if "day" in err.lower() or "daily" in err.lower():
                        slot.quota_hit = True
                        log.warning("Key …%s: DAILY quota exhausted", slot.key[-6:])
                    else:
                        backoff = 15 * (2 ** attempt) + random.uniform(0, 5)
                        slot.backoff_until = time.monotonic() + backoff
                        log.warning("Key …%s: rate-limited. Backoff %.0fs", slot.key[-6:], backoff)
                    continue
                log.error("Gemini ERROR [%s]: %s", slot.key[-6:], e)
                return f"[AI error: {e}]"

    return (
        "[QUOTA_EXCEEDED] All Gemini API keys reached their rate limit. "
        "Please wait 1–2 minutes and try again, or add a free Groq key "
        "(GROQ_API_KEY) from https://console.groq.com for unlimited free access."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED CALLER — routes to Groq first, falls back to Gemini
# ═══════════════════════════════════════════════════════════════════════════════

async def _call_ai(
    prompt: str,
    image_b64_list: Optional[List[str]] = None,
    max_tokens: int = 2048,
) -> str:
    """
    Routes to Groq (primary) or Gemini (fallback).
    Images are only supported via Gemini; Groq gets text-only prompt.
    """
    if USE_GROQ:
        if image_b64_list:
            # Groq doesn't support image input — use Gemini for images if keys exist
            if ALL_KEYS:
                return await _call_gemini(prompt, image_b64_list)
            else:
                return "[Image analysis not available without Gemini API key]"
        return await _call_groq(prompt, max_tokens=max_tokens)

    # Gemini path
    if ALL_KEYS:
        return await _call_gemini(prompt, image_b64_list)

    return "[ERROR] No AI backend configured. Set GROQ_API_KEY or GEMINI_API_KEY in .env"


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC AI FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. Image description ──────────────────────────────────────────────────────
async def describe_image(b64: str) -> str:
    prompt = (
        "You are analyzing a figure or image from a research paper. "
        "Describe what this image shows in 2-3 sentences. "
        "Focus on data, charts, diagrams, or visual information relevant to research."
    )
    return await _call_ai(prompt, [b64])


# ── 2. Chunk summarization ────────────────────────────────────────────────────
async def _summarize_chunk(chunk: Chunk, chunk_num: int, total: int) -> str:
    log.info("Summarizing chunk %d/%d (pages %s)", chunk_num, total, chunk.page_range)
    prompt = (
        f"You are reading section {chunk_num}/{total} (pages {chunk.page_range}) of a research paper.\n\n"
        f"TEXT CONTENT:\n{chunk.text[:3000]}\n\n"
        "Summarize the KEY points in 3-5 bullet points. Be concise."
    )
    return await _call_ai(prompt)


async def summarize_paper(chunks: List[Chunk], title: str) -> str:
    """
    Sequential chunk summarization → consolidated summary.
    Caps at 8 chunks for speed. Total calls = min(len, 8) + 1.
    """
    log.info("Starting summary for '%s' (%d chunks)", title, len(chunks))
    work_chunks = chunks[:8]

    chunk_summaries: List[str] = []
    for i, c in enumerate(work_chunks):
        s = await _summarize_chunk(c, i + 1, len(work_chunks))
        chunk_summaries.append(s)
        if i < len(work_chunks) - 1:
            await asyncio.sleep(1)   # small pause between chunks

    valid = [
        (i, s) for i, s in enumerate(chunk_summaries)
        if isinstance(s, str) and not s.startswith("[AI error") and not s.startswith("[QUOTA") and not s.startswith("[GROQ")
    ]
    log.info("Got %d/%d valid chunk summaries", len(valid), len(work_chunks))

    if not valid:
        return "**Summary generation failed.** Check your API keys in `.env`."

    combined = "\n\n".join(
        f"[Section {i+1}, Pages {work_chunks[i].page_range}]:\n{s}"
        for i, s in valid
    )

    consolidation_prompt = (
        f"You have been given section-by-section summaries of a research paper titled: '{title}'.\n\n"
        f"{combined[:8000]}\n\n"
        "Write a comprehensive summary of the ENTIRE paper covering:\n"
        "1. **Objective / Problem Statement**\n"
        "2. **Methodology / Approach**\n"
        "3. **Key Findings / Results**\n"
        "4. **Contributions / Novelty**\n"
        "5. **Limitations / Future Work**\n\n"
        "Format using markdown with bold headers. Be factual and precise."
    )
    log.info("Running consolidation call…")
    result = await _call_ai(consolidation_prompt, max_tokens=3000)
    log.info("Summary complete!")
    return result


# ── 3. Chatbot Q&A (RAG) ─────────────────────────────────────────────────────
def _retrieve_relevant_chunks(question: str, chunks: List[Chunk], top_k: int = 4) -> List[Chunk]:
    q_words = set(question.lower().split())
    scored  = []
    for chunk in chunks:
        text_lower = chunk.text.lower()
        score = sum(1 for w in q_words if w in text_lower and len(w) > 3)
        scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]] or chunks[:top_k]


async def answer_question(
    question: str,
    chunks: List[Chunk],
    history: List[ChatMessage],
    title: str,
    summary: str,
) -> Dict[str, Any]:
    relevant      = _retrieve_relevant_chunks(question, chunks)
    context_parts = [f"[Pages {c.page_range}]\n{c.text}" for c in relevant]
    context       = "\n\n---\n\n".join(context_parts)

    history_text = "\n".join(
        f"{m.role.upper()}: {m.content}" for m in history[-6:]
    )

    prompt = (
        f"You are an expert research assistant analyzing a paper titled: '{title}'.\n\n"
        f"PAPER SUMMARY:\n{summary[:2000]}\n\n"
        f"RELEVANT EXCERPTS FROM PAPER:\n{context[:4000]}\n\n"
        f"CONVERSATION HISTORY:\n{history_text}\n\n"
        f"USER QUESTION: {question}\n\n"
        "Answer accurately based on the paper content. "
        "If the answer is not in the paper, say so clearly. "
        "Cite specific page numbers when possible (e.g., 'As mentioned on page 3…'). "
        "Format your response in clear markdown."
    )

    answer    = await _call_ai(prompt, max_tokens=2048)
    page_refs = list({c.page_range for c in relevant})
    return {"reply": answer, "page_refs": page_refs}


# ── 4. Publication Review ─────────────────────────────────────────────────────
async def review_paper(full_text: str, title: str) -> Dict[str, Any]:
    text_sample = full_text[:12000] if len(full_text) > 12000 else full_text

    prompt = (
        f"You are a senior academic peer reviewer evaluating the research paper: '{title}'.\n\n"
        f"PAPER CONTENT:\n{text_sample}\n\n"
        "Provide a thorough peer review with the following EXACT structure:\n\n"
        "## VERDICT\n"
        "State: ACCEPT / MINOR REVISION / MAJOR REVISION / REJECT\n\n"
        "## OVERALL SCORE\n"
        "Provide a score from 1–10 for each dimension:\n"
        "- Novelty: X/10\n"
        "- Methodology: X/10\n"
        "- Clarity: X/10\n"
        "- Results: X/10\n"
        "- Overall: X/10\n\n"
        "## STRENGTHS\n"
        "List 3–5 specific strengths.\n\n"
        "## WEAKNESSES\n"
        "List 3–5 specific weaknesses.\n\n"
        "## IMPROVEMENT STEPS\n"
        "Provide a numbered, actionable list of exactly 5–8 steps to improve this paper "
        "before submission. Be very specific.\n\n"
        "## RECOMMENDATION DETAILS\n"
        "Write 2–3 paragraphs explaining your recommendation in detail."
    )

    raw = await _call_ai(prompt, max_tokens=3000)
    return {"raw_review": raw, "title": title}


# ── 5. Conference suggestions ─────────────────────────────────────────────────
async def generate_conference_suggestions(
    title: str, abstract: str, search_results: List[Dict]
) -> List[Dict]:
    search_text = "\n".join(
        f"- {r.get('title','')}: {r.get('url','')}" for r in search_results[:15]
    )

    prompt = (
        f"Research paper: '{title}'\n"
        f"Abstract/summary: {abstract[:1500]}\n\n"
        f"Here are potentially relevant conferences/journals found via web search:\n"
        f"{search_text}\n\n"
        "Based on the research topic, suggest the TOP 6 most relevant publication venues. "
        "For each venue:\n"
        "1. Name\n"
        "2. Type (Conference / Journal / Workshop)\n"
        "3. Why this paper fits\n"
        "4. Impact/Ranking (if known)\n"
        "5. Submission deadline hint (if known, else say 'Check website')\n\n"
        "Format as a numbered list. Be specific and helpful."
    )

    raw = await _call_ai(prompt, max_tokens=2000)
    return [{"raw": raw}]


# ── 6. Similar papers ─────────────────────────────────────────────────────────
async def generate_similar_papers(
    title: str, abstract: str, search_results: List[Dict]
) -> List[Dict]:
    search_text = "\n".join(
        f"- {r.get('title','')}: {r.get('url','')}" for r in search_results[:20]
    )

    prompt = (
        f"Research paper: '{title}'\n"
        f"Summary: {abstract[:1500]}\n\n"
        f"Related papers found via web search:\n"
        f"{search_text}\n\n"
        "Select and present the 7 MOST RELEVANT similar papers. "
        "For each paper provide:\n"
        "1. Paper title\n"
        "2. Why it is similar/related\n"
        "3. Key difference from the uploaded paper\n"
        "4. URL (from the search results above, use exact URL)\n\n"
        "Format as a numbered list. Only include real papers from the search results."
    )

    raw = await _call_ai(prompt, max_tokens=2000)
    return [{"raw": raw}]


# ── 7. Image enrichment (background task) ─────────────────────────────────────
async def enrich_chunks_with_image_descriptions(chunks: List[Chunk]) -> None:
    image_tasks = []
    for chunk in chunks:
        images = getattr(chunk, "_images_b64", [])
        for b64 in images[:1]:
            if len(image_tasks) >= 4:
                break
            image_tasks.append((chunk, b64))

    if not image_tasks:
        log.info("No images to enrich.")
        return

    log.info("Enriching %d images in background…", len(image_tasks))
    for i, (chunk, b64) in enumerate(image_tasks):
        desc = await describe_image(b64)
        if isinstance(desc, str) and not desc.startswith("[AI error") and not desc.startswith("[QUOTA"):
            chunk.image_descriptions.append(desc)
            chunk.text += f"\n\n[Figure Description: {desc}]"
        if i < len(image_tasks) - 1:
            await asyncio.sleep(2)

    log.info("Image enrichment complete.")


# ── Expose key-slot info for /keys endpoint (Gemini only) ────────────────────
# (Groq doesn't need slots; always available)
