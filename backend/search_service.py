"""
search_service.py
Web search using Tavily API for conferences and similar papers.
Falls back to a Gemini-only mode if no API key is set.
"""
import os
import httpx
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"


async def _tavily_search(query: str, max_results: int = 10) -> List[Dict]:
    """Perform a Tavily web search and return result list."""
    if not TAVILY_API_KEY:
        return []

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.post(TAVILY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except Exception as e:
            print(f"[search_service] Tavily error: {e}")
            return []


async def search_conferences(title: str, keywords: str) -> List[Dict]:
    """
    Search for academic conferences related to the research paper's topic.
    Returns list of {title, url, content} dicts.
    """
    queries = [
        f"top academic conferences {keywords} research 2024 2025",
        f"best journals conferences to publish {title[:80]} research",
        f"IEEE ACM conference {keywords} submission 2025",
    ]

    all_results: List[Dict] = []
    for q in queries:
        results = await _tavily_search(q, max_results=6)
        all_results.extend(results)

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append({"title": r.get("title", ""), "url": url, "snippet": r.get("content", "")[:300]})

    return unique


async def search_similar_papers(title: str, abstract_keywords: str) -> List[Dict]:
    """
    Search for similar research papers using Tavily (Google Scholar index).
    Returns list of {title, url, content} dicts.
    """
    queries = [
        f'"{abstract_keywords[:60]}" research paper site:arxiv.org OR site:scholar.google.com',
        f"similar research papers {title[:70]} arxiv",
        f"related work {abstract_keywords[:50]} deep learning / machine learning paper",
    ]

    all_results: List[Dict] = []
    for q in queries:
        results = await _tavily_search(q, max_results=7)
        all_results.extend(results)

    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append({"title": r.get("title", ""), "url": url, "snippet": r.get("content", "")[:300]})

    return unique
