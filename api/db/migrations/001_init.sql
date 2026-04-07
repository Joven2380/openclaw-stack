-- ─────────────────────────────────────────────────────────────────────────────
-- 001_init.sql — core tables
-- Runs automatically on first `docker compose up` via initdb.d mount
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Clients ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS clients (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT        NOT NULL,
    api_key_hash     TEXT        UNIQUE NOT NULL,
    plan             TEXT        DEFAULT 'starter',
    daily_budget_usd NUMERIC(8,2) DEFAULT 5.00,
    is_active        BOOLEAN     DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── Task logs ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS task_logs (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    TEXT         NOT NULL DEFAULT 'internal',
    agent_name   TEXT         NOT NULL,
    model        TEXT         NOT NULL,
    provider     TEXT         NOT NULL DEFAULT 'unknown',
    tokens_in    INT          NOT NULL DEFAULT 0,
    tokens_out   INT          NOT NULL DEFAULT 0,
    cost_usd     NUMERIC(10,6) NOT NULL DEFAULT 0,
    duration_ms  INT          NOT NULL DEFAULT 0,
    success      BOOLEAN      DEFAULT true,
    error_detail TEXT,
    created_at   TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_logs_client_id   ON task_logs (client_id);
CREATE INDEX IF NOT EXISTS idx_task_logs_created_at  ON task_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_task_logs_agent_name  ON task_logs (agent_name);

-- ── Agent sessions ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_sessions (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id    TEXT        NOT NULL DEFAULT 'internal',
    agent_name   TEXT        NOT NULL,
    session_data JSONB       DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── Cost events ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cost_events (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id        TEXT         NOT NULL DEFAULT 'internal',
    date             DATE         NOT NULL DEFAULT CURRENT_DATE,
    model            TEXT         NOT NULL,
    total_tokens_in  INT          DEFAULT 0,
    total_tokens_out INT          DEFAULT 0,
    total_cost_usd   NUMERIC(10,6) DEFAULT 0,
    request_count    INT          DEFAULT 0,
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (client_id, date, model)
);

CREATE INDEX IF NOT EXISTS idx_cost_events_client_date ON cost_events (client_id, date);
CREATE INDEX IF NOT EXISTS idx_cost_events_date        ON cost_events (date);
