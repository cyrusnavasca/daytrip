-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Users
CREATE TABLE IF NOT EXISTS users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trips
CREATE TABLE IF NOT EXISTS trips (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID REFERENCES users(id) ON DELETE SET NULL,
  query          TEXT NOT NULL,
  itinerary_json JSONB,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Retrieval cache (runtime RAG — embed only retrieved subset)
CREATE TABLE IF NOT EXISTS retrieval_cache (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source     TEXT NOT NULL,               -- 'reddit' | 'yelp' | 'google_places' | 'tavily'
  content    TEXT NOT NULL,
  embedding  vector(1536),                -- OpenAI text-embedding-3-small dimension
  city       TEXT,
  category   TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast ANN search within a city
CREATE INDEX IF NOT EXISTS retrieval_cache_embedding_idx
  ON retrieval_cache
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE INDEX IF NOT EXISTS retrieval_cache_city_idx
  ON retrieval_cache (city);

-- User preferences
CREATE TABLE IF NOT EXISTS user_preferences (
  user_id      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  vibe_tags    TEXT[]  DEFAULT '{}',
  disliked_tags TEXT[] DEFAULT '{}',
  budget_range NUMRANGE
);
