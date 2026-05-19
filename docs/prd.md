# AI Day Trip Planner — PRD

## 1. Overview

A consumer-facing web app that generates personalized day-trip itineraries via agentic tool orchestration, live search, runtime RAG, and route optimization. Should feel dynamic, local, and practical — not like a generic travel chatbot.

---

## 2. File Structure

```
daytrip/
├── docs/
│   ├── prd.md
│   └── dev-plan.md
│
├── src/                                  # Next.js frontend (TypeScript)
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx                    # Root layout, fonts, metadata
│   │   ├── page.tsx                      # Landing page — prompt input form
│   │   └── trip/
│   │       └── [id]/
│   │           └── page.tsx              # Itinerary results page
│   ├── components/
│   │   ├── ui/                           # shadcn/ui primitives (auto-generated)
│   │   ├── TripForm.tsx                  # Main input form (location, budget, vibe…)
│   │   ├── ItineraryCard.tsx             # Single stop display card
│   │   ├── ItineraryMap.tsx              # Mapbox GL interactive map
│   │   └── StreamingOutput.tsx           # Renders streamed SSE itinerary text
│   ├── hooks/
│   │   ├── useTripStream.ts              # SSE streaming hook → FastAPI /plan
│   │   └── useMapbox.ts                  # Mapbox GL initialization + markers
│   ├── lib/
│   │   ├── api.ts                        # Typed fetch wrappers → FastAPI
│   │   ├── db.ts                         # Direct DB helpers (if needed client-side)
│   │   ├── env.ts                        # Env var validation (t3-env or manual)
│   │   └── utils.ts                      # cn() and shared utilities
│   └── types/
│       └── index.ts                      # Shared TypeScript interfaces & types
│
├── backend/                              # FastAPI Python service
│   ├── app/
│   │   ├── main.py                       # FastAPI app entry, CORS, router mount
│   │   ├── api/
│   │   │   └── routes.py                 # POST /plan → streams itinerary response
│   │   ├── agents/
│   │   │   ├── orchestrator.py           # LangGraph graph definition & state
│   │   │   ├── search_agent.py           # Query generation + external retrieval
│   │   │   ├── rag_agent.py              # Chunk → embed subset → semantic rerank
│   │   │   ├── ranking_agent.py          # Score candidates (vibe, cost, time)
│   │   │   └── routing_agent.py          # Stop order optimization + travel times
│   │   ├── tools/
│   │   │   ├── google_places.py          # Places search + reviews
│   │   │   ├── reddit.py                 # Reddit PRAW retrieval
│   │   │   ├── mapbox.py                 # Directions + travel time estimates
│   │   │   ├── openweather.py            # Weather-aware planning data
│   │   │   └── atlas_obscura.py          # Hidden/unique local spots by lat/lng
│   │   ├── models/
│   │   │   ├── request.py                # Pydantic: TripRequest schema
│   │   │   └── response.py               # Pydantic: Itinerary + Stop schemas
│   │   └── db/
│   │       ├── client.py                 # asyncpg connection pool setup
│   │       └── queries.py                # Typed SQL helpers (cache, trips, users)
│   ├── requirements.txt
│   └── .env                              # Backend secrets (gitignored)
│
├── scripts/
│   ├── migrate.js                        # Run DB migrations
│   └── schema.sql                        # PostgreSQL schema (users, trips, cache)
│
├── .env.example                          # Template for all required env vars
├── .env.local                            # Local dev overrides (gitignored)
├── .gitignore
├── components.json                       # shadcn/ui config
├── next.config.ts
├── package.json
├── postcss.config.mjs
├── tailwind.config.ts
├── tsconfig.json
└── vercel.json
```

---

## 3. User Experience

**Input:** starting location, budget, transport type, trip duration, vibe/preferences, optional constraints.

> *"Fun solo coastal day trip near Santa Barbara under $100"*

**Output:** ordered itinerary with timing, travel estimates, food/activity recommendations, explanations, and backup alternatives.

```
10:00 AM — Coffee at Handlebar
12:00 PM — Explore Funk Zone
3:00 PM  — Shoreline Park coastal walk
6:45 PM  — Sunset at Butterfly Beach
```

---

## 4. Architecture

```
Next.js Frontend (Vercel)
        ↓  POST /api/plan
FastAPI Backend (Railway/Render)  ← Python
        ↓
Orchestrator Agent (LangGraph)
        ↓
┌─────────────────────┐
│ Search Agent        │
│ Retrieval/RAG Agent │
│ Ranking Agent       │
│ Routing Agent       │
│ Constraint Checker  │
└─────────────────────┘
        ↓
Final LLM Synthesis (GPT-4o) → Streamed Response → Frontend
```

---

## 5. Sequential Workflow

1. **User Query** — natural language trip request
2. **Constraint Extraction** — parse to structured state (`location`, `budget`, `vibe`, `transport`)
3. **Search Query Generation** — agent generates targeted queries (e.g., `best sunset spots malibu reddit`)
4. **Tool Calls** — Reddit, Maps, Atlas Obscura, Weather APIs in parallel
5. **Runtime RAG** — chunk → embed retrieved subset → semantic rerank
6. **Ranking** — score candidates on vibe match, distance, cost, sentiment, uniqueness, time feasibility
7. **Route Planning** — optimize order, check hours, travel times, pacing, budget
8. **Final Synthesis** — LLM generates readable itinerary with explanations and alternatives
9. **Replanning Loop** *(optional)* — re-trigger if weather changes, traffic spikes, or user skips a stop

---

## 6. Agent System

| Agent | Responsibilities | Tools/APIs |
|---|---|---|
| **Orchestrator** | Manage workflow state, invoke tools, coordinate subagents | — |
| **Search** | Generate queries, retrieve external info | Tavily (incl. Reddit via `site:reddit.com`), Google Places, Atlas Obscura |
| **Retrieval/RAG** | Chunk text, embed subset, semantic rerank, return top context | pgvector / Qdrant |
| **Ranking** | Score candidates on vibe, reviews, efficiency, uniqueness | — |
| **Routing** | Optimize stop order, compute travel times | Google Directions, Mapbox |
| **Reflection** *(optional)* | Validate realism, flag poor pacing or duplicates | — |

> **RAG note:** Only embed the retrieved subset + cached docs — never pre-index the entire internet.

---

## 7. Tech Stack

| Layer | Choice |
|---|---|
| **Frontend** | Next.js (TypeScript), Tailwind, shadcn/ui, Mapbox GL |
| **Frontend Hosting** | Vercel |
| **Backend** | FastAPI (Python) |
| **Backend Hosting** | Railway or Render |
| **Agent Framework** | LangGraph (Python) |
| **LLM** | OpenAI GPT-4o |
| **Embeddings** | OpenAI `text-embedding-3-small` |
| **Database** | PostgreSQL + pgvector (Neon) |
| **DB Driver** | `asyncpg` / `psycopg3` |

> **Architecture:** Next.js handles all UI. FastAPI runs as a separate service and owns all agent logic, LLM calls, and database access. The frontend communicates with FastAPI via a single `/api/plan` POST endpoint.

---

## 8. External APIs

- **Google Places / Directions** — location data, reviews, routing
- **Mapbox Directions** — alternate routing + interactive map
- **Atlas Obscura** (`atlas-obscura-api` npm, no key) — unique/hidden local spots searched by lat/lng
- **Tavily** — agentic web search; Reddit threads retrieved via `site:reddit.com` queries (Reddit's API is closed to new developers)
- **OpenWeather** — weather-aware planning
- ~~**Yelp Fusion**~~ *(dropped — requires business email; coverage replaced by Google Places + Atlas Obscura)*

---

## 9. Database Schema

```sql
users              (id, email, created_at)
trips              (id, user_id, query, itinerary_json, created_at)
retrieval_cache    (id, source, content, embedding, city, category, created_at)
user_preferences   (user_id, vibe_tags, disliked_tags, budget_range)
```

---

## 10. MVP Scope

**Required:**
- Trip prompt → itinerary generation
- Maps integration + route optimization
- Reddit retrieval + semantic reranking
- Budget awareness

**Nice-to-have:**
- Weather-aware replanning
- Saved trips, preference memory, itinerary sharing

**Out of scope (MVP):**
- Booking / hotel reservations
- Social features
- Multi-day optimization
- Distributed scraping or all-city indexing

---

## 11. Latency Strategy

- **Search first, embed later** — retrieve a small subset, then embed only that
- **Parallel API calls** — weather, Maps, and Reddit fire simultaneously
- **Caching** — popular searches, Reddit threads, embeddings, and itineraries
- **SQL pre-filter** — filter by city before vector search

---

## 12. Future Features

- **Collaborative planning** — multiple users vote on preferences
- **Learning personalization** — adapt to liked/disliked trips over time
- **Vibe parsing** — extract aesthetics from TikTok/Pinterest uploads
- **Real-time replanning** — dynamic updates for weather, closures, traffic

---

## 13. Success Metrics

**Product:** itinerary completion rate, saved/shared trips, repeat users, ratings

**AI:** retrieval relevance, itinerary feasibility, route efficiency, personalization quality

---

## 14. Key Engineering Challenges

1. Avoid generic tourist recommendations — prioritize local/Reddit signal
2. Maintain low latency across multiple concurrent tool calls
3. Generate realistic, time-feasible itineraries
4. Handle noisy, unstructured Reddit/blog data in retrieval
