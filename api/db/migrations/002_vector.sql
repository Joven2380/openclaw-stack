-- ─────────────────────────────────────────────────────────────────────────────
-- 002_vector.sql — pgvector extension and agent memory table
-- Runs after 001_init.sql (alphabetical order via initdb.d)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Agent memories ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_memories (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    namespace  TEXT        NOT NULL,   -- format: "{client_id}:{agent_name}"
    client_id  TEXT        NOT NULL DEFAULT 'internal',
    agent_name TEXT        NOT NULL,
    content    TEXT        NOT NULL,
    embedding  vector(1536),
    metadata   JSONB       DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_namespace  ON agent_memories (namespace);
CREATE INDEX IF NOT EXISTS idx_agent_memories_client_id  ON agent_memories (client_id);

-- IVFFlat index for fast approximate cosine similarity search
-- lists=100 is a good default; tune upward when row count exceeds ~1M
CREATE INDEX IF NOT EXISTS idx_agent_memories_embedding
    ON agent_memories
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
