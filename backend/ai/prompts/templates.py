"""
ai/prompts/templates.py
─────────────────────────────────────────────────────────────────────────────
All prompt templates as pure functions.
Keeping prompts separate from business logic makes them easy to iterate on
without touching any AI or routing code.
─────────────────────────────────────────────────────────────────────────────
"""
from typing import List


# ── Image description ────────────────────────────────────────────────────────

def image_description_prompt() -> str:
    return (
        "You are analyzing a figure or image from a research paper. "
        "Describe what this image shows in 2–3 sentences. "
        "Focus on data, charts, diagrams, or visual information relevant to research."
    )


# ── Chunk-level summarization ────────────────────────────────────────────────

def chunk_summary_prompt(chunk_num: int, total: int, page_range: str, text: str) -> str:
    return (
        f"You are reading section {chunk_num}/{total} "
        f"(pages {page_range}) of a research paper.\n\n"
        f"TEXT CONTENT:\n{text[:3000]}\n\n"
        "Summarize the KEY points in 3–5 bullet points. Be concise."
    )


# ── Paper-level consolidation ────────────────────────────────────────────────

def paper_consolidation_prompt(title: str, combined_summaries: str) -> str:
    return (
        f"You have been given section-by-section summaries of a research paper "
        f"titled: '{title}'.\n\n"
        f"{combined_summaries[:8000]}\n\n"
        "Write a comprehensive summary of the ENTIRE paper covering:\n"
        "1. **Objective / Problem Statement**\n"
        "2. **Methodology / Approach**\n"
        "3. **Key Findings / Results**\n"
        "4. **Contributions / Novelty**\n"
        "5. **Limitations / Future Work**\n\n"
        "Format using markdown with bold headers. Be factual and precise."
    )


# ── RAG Q&A ──────────────────────────────────────────────────────────────────

def rag_answer_prompt(
    title: str,
    summary: str,
    context: str,
    history_text: str,
    question: str,
) -> str:
    return (
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


# ── Peer Review ───────────────────────────────────────────────────────────────

def peer_review_prompt(title: str, text_sample: str) -> str:
    return (
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


# ── Conference suggestions ────────────────────────────────────────────────────

def conference_suggestion_prompt(
    title: str, abstract: str, search_text: str
) -> str:
    return (
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


# ── Similar papers ────────────────────────────────────────────────────────────

def similar_papers_prompt(
    title: str, abstract: str, search_text: str
) -> str:
    return (
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
