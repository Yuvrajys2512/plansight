CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS drawings (
  id text PRIMARY KEY, source text NOT NULL, image_url text, width integer, height integer,
  sheet_text text NOT NULL DEFAULT '', embedding vector(384), metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS regions (
  id bigserial PRIMARY KEY, drawing_id text NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
  bbox real[] NOT NULL, label text NOT NULL DEFAULT '', kind text NOT NULL DEFAULT '', metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS regions_drawing_kind_idx ON regions(drawing_id, kind);
CREATE TABLE IF NOT EXISTS facts (
  id bigserial PRIMARY KEY, drawing_id text NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
  key text NOT NULL, value jsonb NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(drawing_id,key)
);
CREATE TABLE IF NOT EXISTS answer_cache (
  cache_key text PRIMARY KEY, drawing_path text NOT NULL, question text NOT NULL,
  answer jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS question_log (
  id bigserial PRIMARY KEY, asked_at timestamptz NOT NULL DEFAULT now(), drawing_path text NOT NULL,
  question text NOT NULL, solver text, abstained boolean NOT NULL, cached boolean NOT NULL DEFAULT false,
  answer jsonb, cost_usd double precision NOT NULL DEFAULT 0, naive_cost_usd double precision NOT NULL DEFAULT 0,
  latency_ms double precision NOT NULL DEFAULT 0, evidence_count integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS corrections (
  id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(), plan text NOT NULL,
  kind text NOT NULL, bbox real[] NOT NULL, action text NOT NULL
);
