# CLAUDE CODE PROMPT — OpenClaw Repo
# Paste this into Antigravity when you have the openclaw-stack folder open
# This is Phase A: Wire Jake to OPS-AI

---

## Context (read this first, don't skip)

Read docs/ARCHITECTURE.md first — it has the full system map.

We have three separated systems:
1. **OpenClaw (this repo)** — Jake's home, on Hetzner (5.223.94.137, bottleneck-ai.com)
2. **OPS-AI** — Fleet management ERP on Railway (ops-ai-production.up.railway.app)
3. **n8n** — Worker bot automation on Railway

Jake is the AI overseer. He needs to READ data from OPS-AI via its API, and TRIGGER n8n workflows via webhooks. He does NOT replace the OPS-AI worker bots.

Currently Jake's tools (query_fleet, query_trips, query_fuel) query the LOCAL Hetzner Postgres, which has NO business data. We need to rewire them to call the OPS-AI API on Railway instead.

---

## Step 1: Add the architecture doc

Create `docs/ARCHITECTURE.md` in the repo root with the contents of the file I'll provide. This is our shared context document that prevents us from losing track of what we're building.

## Step 2: Add OPS-AI env vars

Add these to `.env` on the server AND to `.env.example` in the repo:

```
# ── OPS-AI Bridge ────────────────────────────────────────────────────────────
OPSAI_API_URL=https://ops-ai-production.up.railway.app
OPSAI_API_KEY=        # Get this from Railway: ops-ai service → Variables → BOT_API_KEY

# ── n8n Webhooks ─────────────────────────────────────────────────────────────
N8N_BASE_URL=https://n8n-production-3eb7.up.railway.app
N8N_WEBHOOK_DAILY_DIGEST=
N8N_WEBHOOK_MANAGER_ALERTS=
```

Also update `api/core/config.py` (the Settings class) to include:
```python
OPSAI_API_URL: str = ""
OPSAI_API_KEY: str = ""
N8N_BASE_URL: str = ""
N8N_WEBHOOK_DAILY_DIGEST: str = ""
N8N_WEBHOOK_MANAGER_ALERTS: str = ""
```

## Step 3: Create an OPS-AI HTTP client

Create a new file `api/core/opsai_client.py` — a simple async HTTP client that:
- Takes the OPSAI_API_URL and OPSAI_API_KEY from config
- Makes GET/POST requests to OPS-AI endpoints  
- Adds the `X-Bot-Key` header for auth
- Has proper error handling and timeout (15s)
- Returns parsed JSON

Something like:
```python
async def opsai_get(path: str, params: dict | None = None) -> dict:
    """GET from OPS-AI API. Path like '/api/v1/trips'"""
    
async def opsai_post(path: str, body: dict | None = None) -> dict:
    """POST to OPS-AI API."""
```

## Step 4: Rewrite the tools in registry.py

Replace the current tool implementations that query local tables with ones that call OPS-AI:

### Rewrite `query_fleet`:
- Call `opsai_get("/api/v1/trucks")`
- Return the truck list from OPS-AI
- Keep the same tool name and schema so jake.yaml doesn't need changes

### Rewrite `query_trips`:
- Call `opsai_get("/api/v1/trips", params={"start_date": ..., "end_date": ...})`
- Accept optional date filters from the LLM
- Return trip data from OPS-AI

### Rewrite `query_fuel`:
- Call `opsai_get("/api/v1/reports/fuel-efficiency")`
- Return fuel data from OPS-AI

### Add NEW tool `get_kpi_summary`:
- Call `opsai_get("/api/v1/kpis/summary")`
- Returns weekly KPI dashboard data (total trips, tonnage, active trucks, etc.)
- Add to TOOL_REGISTRY and TOOL_SCHEMAS

### Add NEW tool `get_daily_report`:  
- Call `opsai_get("/api/v1/reports/daily-summary")`
- Returns today's operations summary
- Add to TOOL_REGISTRY and TOOL_SCHEMAS

### Add NEW tool `get_pending_approvals`:
- Call `opsai_get("/api/v1/bot/pending-approvals")`
- Returns receipts waiting for review
- Add to TOOL_REGISTRY and TOOL_SCHEMAS

### Rewrite `trigger_n8n_webhook`:
- Read webhook URLs from config (N8N_WEBHOOK_DAILY_DIGEST etc.)
- POST to the real n8n webhook URL
- Validate against approved webhook list
- Return success/failure

### Keep unchanged:
- `escalate` — works as-is
- `send_telegram` — works as-is
- `classify_intent` — works as-is

## Step 5: Update jake.yaml

Add the new tools to Jake's tools list:
```yaml
tools:
  - query_fleet
  - query_trips
  - query_fuel
  - get_kpi_summary
  - get_daily_report
  - get_pending_approvals
  - trigger_n8n_webhook
  - escalate
  - send_telegram
```

## Step 6: Update SOUL.md

Add a section to SOUL.md defining Jake's overseer role:

```markdown
## Jake's Role

You are Jake, the Operations Manager AI for Bottleneck (bottleneck-ai.com).
You serve as Job Pangilinan's personal AI executive assistant.

Your scope:
- RPQ Truckwide Corp fleet operations (via OPS-AI tools)
- JM-TECH ECU diagnostics venture  
- Bottleneck AI platform strategy
- General business advisory

When asked about fleet/operations data:
- ALWAYS use your tools to get real data from OPS-AI
- Never guess numbers — if a tool returns empty, say "no data found"
- If a tool errors, explain what happened and suggest alternatives

When asked to run workflows:
- Use trigger_n8n_webhook to fire the requested workflow
- Confirm with Job before triggering anything that sends messages to others

Communication:
- Default to English for data/technical responses
- Switch to Taglish when Job messages in Taglish
- Keep responses concise — you're talking to a busy operator on Telegram
```

## Step 7: Test

1. SSH into the server: `ssh root@5.223.94.137`
2. Pull the latest code: `cd /root/openclaw-stack && git pull`
3. Add the OPSAI env vars to the server .env: `nano .env`
4. Restart the app: `docker compose up -d --force-recreate app`
5. Message Jake on Telegram: "How many trucks do we have?"
6. Check logs: `docker compose logs app -f | grep -E "tool|opsai|error"`
7. Verify Jake calls OPS-AI API and returns real data

## Step 8: Commit

```bash
git add -A && git commit -m "Phase A: Wire Jake to OPS-AI API — tools now query real business data" && git push
```

---

## Important notes

- DO NOT remove the existing local DB tools (query_fleet etc.) — rewrite them in place
- DO NOT change the tool names — jake.yaml already references them
- DO NOT touch agent_runner.py — the tool execution loop is already working
- The OPSAI_API_KEY must match the BOT_API_KEY in Railway's ops-ai service variables
- All OPS-AI endpoints use /api/v1/ prefix
- Error responses from OPS-AI should be passed back to the LLM so Jake can explain what went wrong
