# ResearchLens AI 🔬

An AI-powered research paper analysis platform built with **FastAPI** + **Google Gemini 1.5 Pro**.

## Features
| Feature | Description |
|---|---|
| 📝 Summary | Auto-generated structured summary on upload |
| 💬 Chatbot | Ask questions about the paper (RAG with page citations) |
| 📋 Peer Review | Expert review with scores, strengths, weaknesses, steps |
| 🏛️ Conferences | Suggested publication venues via web search |
| 🔗 Similar Papers | 7+ related papers discovered from the web |

## Architecture

```
BTP-2/
├── backend/
│   ├── main.py            # FastAPI routes
│   ├── pdf_processor.py   # PyMuPDF extraction + chunking
│   ├── ai_service.py      # Gemini calls + Semaphore rate limiting
│   ├── search_service.py  # Tavily web search
│   ├── session_store.py   # In-memory sessions
│   └── requirements.txt
├── frontend/
│   ├── index.html         # Single Page App
│   ├── style.css          # Premium dark-mode design
│   └── app.js             # API calls + UI logic
└── .env                   # API keys
```

## Setup

### 1. Get API Keys
- **Gemini API**: https://aistudio.google.com/app/apikey (free)
- **Tavily API**: https://tavily.com (free tier: 1000 req/month)

### 2. Configure `.env`
```
GEMINI_API_KEY=your_key_here
TAVILY_API_KEY=your_key_here
```

### 3. Install & Run
```powershell
cd backend
pip install -r requirements.txt
python main.py
```

Then open: **http://localhost:8000**

## How It Works

1. **PDF Upload** → PyMuPDF extracts text page-by-page, detects tables (heuristic), extracts images as base64
2. **Chunking** → Smart 4000-char chunks with 400-char overlap at paragraph/sentence boundaries
3. **Image enrichment** → Gemini Vision describes each image; descriptions embedded in chunks
4. **Summary** → All chunks summarized in parallel (Semaphore=3), then consolidated
5. **Chat** → Keyword-based RAG retrieves top-4 relevant chunks → Gemini answers with page refs
6. **Review** → First 12,000 chars sent to Gemini with structured review prompt
7. **Conferences** → Tavily searches 3 queries → Gemini curates top 6 venues
8. **Similar Papers** → Tavily searches arXiv/Scholar → Gemini curates top 7 papers

## Rate Limiting
`asyncio.Semaphore(3)` limits concurrent Gemini API calls to avoid quota errors on large papers.
