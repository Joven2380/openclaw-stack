from datetime import date, timedelta

import asyncpg

from api.core.cost_calc import get_provider


async def log_task(
    conn: asyncpg.Connection,
    client_id: str,
    agent_name: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    duration_ms: int,
    success: bool = True,
    error_detail: str | None = None,
) -> str:
    """Inserts a task log row and returns the new UUID as a string."""
    row = await conn.fetchrow(
        """
        INSERT INTO task_logs
            (client_id, agent_name, model, provider,
             tokens_in, tokens_out, cost_usd, duration_ms,
             success, error_detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        client_id,
        agent_name,
        model,
        get_provider(model),
        tokens_in,
        tokens_out,
        cost_usd,
        duration_ms,
        success,
        error_detail,
    )
    return str(row["id"])


async def get_client_daily_spend(
    conn: asyncpg.Connection,
    client_id: str,
    date: date | None = None,
) -> float:
    """Returns total cost_usd for a client on a given date (defaults to today)."""
    target = date or date.today()  # type: ignore[attr-defined]
    # Note: asyncpg date params expect python date objects
    row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(cost_usd), 0) AS total
        FROM task_logs
        WHERE client_id = $1
          AND created_at::date = $2
        """,
        client_id,
        target,
    )
    return float(row["total"])


async def get_client_by_api_key_hash(
    conn: asyncpg.Connection,
    api_key_hash: str,
) -> dict | None:
    """Returns client row as dict or None if not found."""
    row = await conn.fetchrow(
        "SELECT * FROM clients WHERE api_key_hash = $1 AND is_active = true",
        api_key_hash,
    )
    return dict(row) if row else None


async def upsert_cost_event(
    conn: asyncpg.Connection,
    client_id: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    """Atomically increments today's cost event row for client+model."""
    await conn.execute(
        """
        INSERT INTO cost_events
            (client_id, date, model, total_tokens_in, total_tokens_out, total_cost_usd, request_count)
        VALUES ($1, CURRENT_DATE, $2, $3, $4, $5, 1)
        ON CONFLICT (client_id, date, model) DO UPDATE
        SET
            total_tokens_in  = cost_events.total_tokens_in  + EXCLUDED.total_tokens_in,
            total_tokens_out = cost_events.total_tokens_out + EXCLUDED.total_tokens_out,
            total_cost_usd   = cost_events.total_cost_usd   + EXCLUDED.total_cost_usd,
            request_count    = cost_events.request_count    + 1,
            updated_at       = NOW()
        """,
        client_id,
        model,
        tokens_in,
        tokens_out,
        cost_usd,
    )


async def get_cost_summary(
    conn: asyncpg.Connection,
    client_id: str | None = None,
    days: int = 7,
) -> list[dict]:
    """Returns daily cost breakdown for the past N days, grouped by date and model."""
    cutoff = date.today() - timedelta(days=days)

    if client_id is not None:
        rows = await conn.fetch(
            """
            SELECT date, model, client_id,
                   SUM(total_cost_usd)   AS total_cost_usd,
                   SUM(request_count)    AS request_count,
                   SUM(total_tokens_in)  AS total_tokens_in,
                   SUM(total_tokens_out) AS total_tokens_out
            FROM cost_events
            WHERE client_id = $1
              AND date >= $2
            GROUP BY date, model, client_id
            ORDER BY date DESC
            """,
            client_id,
            cutoff,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT date, model,
                   SUM(total_cost_usd)   AS total_cost_usd,
                   SUM(request_count)    AS request_count,
                   SUM(total_tokens_in)  AS total_tokens_in,
                   SUM(total_tokens_out) AS total_tokens_out
            FROM cost_events
            WHERE date >= $1
            GROUP BY date, model
            ORDER BY date DESC
            """,
            cutoff,
        )

    return [dict(row) for row in rows]
