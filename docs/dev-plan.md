# AI Day Trip Planner — Development Plan

> **Tracking:** Check off items with `- [x]` as they are completed. Leave `- [ ]` for anything not yet done or only partially done.

## Phase 1 — Project Setup
- [x] Init Next.js app with TypeScript + Tailwind + shadcn/ui
- [x] Set up PostgreSQL database + pgvector extension
- [x] Configure environment variables (API keys)
- [ ] Deploy skeleton to Vercel

## Phase 2 — Core Backend & Data Layer
- [x] Define DB schema (`users`, `trips`, `retrieval_cache`, `user_preferences`)
- [x] Build `/api/plan` route (accepts user query, returns itinerary)
- [x] Integrate OpenAI SDK (LLM + embeddings)
- [x] Wire up Google Places + Directions APIs
- [x] ~~Wire up Yelp Fusion API~~ *(dropped — replaced by Google Places + Atlas Obscura)*
- [x] Wire up Atlas Obscura API (public endpoint, no key — search by lat/lng, graceful fallback)
- [x] Wire up Reddit API (via Tavily `site:reddit.com` — Reddit API closed to new devs)
- [x] Wire up OpenWeather API

## Phase 3 — Agent System (LangGraph or PydanticAI)
- [x] **Orchestrator Agent** — manages state, invokes subagents in order
- [x] **Search Agent** — generates targeted queries, calls Tavily/SerpAPI + Reddit + Atlas Obscura
- [x] **Retrieval/RAG Agent** — chunks results, embeds subset, semantic reranks via pgvector
- [x] **Ranking Agent** — scores candidates (vibe, cost, distance, sentiment, uniqueness)
- [x] **Routing Agent** — optimizes stop order, computes travel times via Directions API
- [x] **Constraint Checker** — validates budget, hours, pacing
- [x] Run Search + Weather + Maps tool calls in parallel

## Phase 4 — Itinerary Generation
- [x] Final LLM synthesis prompt (readable itinerary + explanations + alternatives)
- [x] Enforce structured output schema (JSON with stops, times, costs)
- [x] Add backup/alternative suggestions per stop

## Phase 5 — Frontend UI
- [ ] Trip input form (location, budget, transport, duration, vibe)
- [ ] Streaming itinerary display (token-by-token or step-by-step)
- [ ] Interactive map with stop markers (Mapbox GL)
- [ ] Loading states + step-progress indicator

## Phase 6 — Caching & Latency Optimization
- [ ] Cache Reddit threads + embeddings in `retrieval_cache`
- [ ] Cache full itineraries for repeated queries
- [ ] SQL city pre-filter before vector search
- [ ] Validate parallel tool call execution

## Phase 7 — Auth & Persistence *(nice-to-have)*
- [ ] User auth (NextAuth or Clerk)
- [ ] Save/view past trips
- [ ] Store user preference profile (`vibe_tags`, `budget_range`)

## Phase 8 — Polish & Launch
- [ ] Error handling + fallbacks for failed API calls
- [ ] Rate limiting on `/api/plan`
- [ ] Add Reflection Agent (validate itinerary realism)
- [ ] Mobile-responsive UI pass
- [ ] Final Vercel production deploy
