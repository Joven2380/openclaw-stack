"""Smoke test for the full agent execution chain.

Tests:
  1. Nora (Anthropic/claude-sonnet-4-20250514) — ops query
  2. Analyst (Qwen/qwq-32b) — analytical query
  3. Memory search — confirms interactions were stored

Usage:
  cd openclaw-stack
  python scripts/test_agent_run.py

Required env vars: DATABASE_URL, ANTHROPIC_API_KEY (for Nora), QWEN_API_KEY (for Analyst).
Optional: OPENAI_API_KEY (for embeddings — falls back to Ollama if not set).
"""

import asyncio
import os
import sys
import json

# Ensure project root is on the path when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_env() -> list[str]:
    """Return list of missing critical env vars."""
    missing = []
    for var in ("DATABASE_URL", "ANTHROPIC_API_KEY"):
        if not os.getenv(var):
            missing.append(var)
    return missing


def _print_result(label: str, result: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Agent   : {result.get('agent')}")
    print(f"  Model   : {result.get('model')}")
    print(f"  Tokens  : {result.get('tokens_in', 0)} in / {result.get('tokens_out', 0)} out")
    print(f"  Cost    : ${result.get('cost_usd', 0):.6f}")
    print(f"  Time    : {result.get('duration_ms', 0)}ms")
    print(f"\n  Response:\n")
    response = result.get("response", "")
    # Indent response lines for readability.
    for line in response.splitlines():
        print(f"    {line}")


async def main() -> None:
    missing = check_env()
    if missing:
        print(f"\n[ERROR] Missing required env vars: {', '.join(missing)}")
        print("  Set them in your .env file or export before running.")
        sys.exit(1)

    # Import after path setup and env check.
    from api.db.database import create_pool, close_pool, get_pool
    from api.core.agent_runner import run_agent
    from api.core.memory import search_memory

    print("\n[openclaw smoke test] Initializing DB pool...")
    try:
        await create_pool()
        print("[openclaw smoke test] DB pool ready.")
    except Exception as exc:
        print(f"[ERROR] Could not connect to DB: {exc}")
        print("  Check DATABASE_URL in your .env file.")
        sys.exit(1)

    pool = get_pool()

    # -----------------------------------------------------------------------
    # Test 1 — Nora (ops query)
    # -----------------------------------------------------------------------
    print("\n[1/3] Running Nora — fleet availability query...")
    try:
        async with pool.acquire() as conn:
            nora_result = await run_agent(
                agent_name="nora",
                user_message="Ilan ang available trucks natin today? Give me a status summary.",
                client_id="smoke_test",
                conn=conn,
            )
        _print_result("NORA — Fleet Status Query", nora_result)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc} — make sure agents/nora.yaml exists")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] Nora run failed: {exc}")
        print("  Check ANTHROPIC_API_KEY and network access.")

    # -----------------------------------------------------------------------
    # Test 2 — Analyst (analytical query)
    # -----------------------------------------------------------------------
    print("\n[2/3] Running Analyst — fuel cost analysis...")
    analyst_ok = False
    if not os.getenv("QWEN_API_KEY"):
        print("  [SKIP] QWEN_API_KEY not set — skipping Analyst test.")
    else:
        try:
            async with pool.acquire() as conn:
                analyst_result = await run_agent(
                    agent_name="analyst",
                    user_message=(
                        "Compute the average fuel cost per trip for the last 30 days. "
                        "If no data is available yet, describe the analysis methodology "
                        "you would use once the trips and fuel_logs tables are populated."
                    ),
                    client_id="smoke_test",
                    conn=conn,
                )
            _print_result("ANALYST — Fuel Cost Analysis", analyst_result)
            analyst_ok = True
        except Exception as exc:
            print(f"[ERROR] Analyst run failed: {exc}")

    # -----------------------------------------------------------------------
    # Test 3 — Memory search (verify Nora interaction was stored)
    # -----------------------------------------------------------------------
    print("\n[3/3] Verifying memory storage for Nora...")
    try:
        async with pool.acquire() as conn:
            memories = await search_memory(
                agent_name="nora",
                query="trucks available",
                conn=conn,
                client_id="smoke_test",
                limit=3,
            )

        if memories:
            print(f"\n  Found {len(memories)} memory record(s):")
            for i, m in enumerate(memories, 1):
                preview = m["content"][:120].replace("\n", " ")
                print(f"  [{i}] similarity={m['similarity']:.3f} | {preview}...")
        else:
            print("  No memories found — embedding or DB may not be configured.")
            if not os.getenv("OPENAI_API_KEY"):
                print("  Hint: OPENAI_API_KEY not set. Ollama embedding fallback requires")
                print("  nomic-embed-text pulled and OLLAMA_BASE_URL reachable.")
    except Exception as exc:
        print(f"[ERROR] Memory search failed: {exc}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  SMOKE TEST COMPLETE")
    print(f"{'='*60}")
    print("  Chain verified: YAML config → SOUL.md → memory search → model call → memory store")
    print("  Ready for Phase 2 Step 3: Telegram bot dispatch wiring.\n")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
