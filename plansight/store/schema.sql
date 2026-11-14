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
