# CLAUDE CODE PROMPT — OPS-AI Repo
# Paste this into Antigravity when you have the ops-ai folder open
# This is Phase C: Harden bot endpoints for Jake

---

## Context (read this first)

Read docs/ARCHITECTURE.md first — it has the full system map.

We have three separated systems:
1. **OpenClaw** — Jake's home on Hetzner. Jake is Job's AI overseer.
2. **OPS-AI (this repo)** — Fleet management ERP on Railway. The source of truth for all business data.
3. **n8n** — Worker bot automation on Railway.

Jake (on OpenClaw) will be calling OPS-AI's API to READ data. He authenticates with the X-Bot-Key header (BOT_API_KEY env var). Jake does NOT write to the database — he only reads.

The n8n worker bots (attendance, receipt upload, purchasing query) continue to operate independently. They don't know Jake exists.

Our job here is to make sure the API endpoints Jake needs exist, return clean JSON, and work with X-Bot-Key auth.

---

## Step 1: Add the architecture doc

Create `docs/ARCHITECTURE.md` in the repo root. I'll provide the contents — it's our shared context document across both repos.

## Step 2: Audit existing bot endpoints

Check what `/api/v1/bot/*` endpoints currently exist and what they return. From the codebase I can see:

```
GET  /api/v1/bot/pending-approvals   — Returns pending receipts
GET  /api/v1/bot/employees           — Returns employee list
POST /api/v1/bot/query               — AI analyst query
POST /api/v1/bot/receipt-upload      — Upload receipt photo
POST /api/v1/bot/attendance          — Log attendance
POST /api/v1/bot/link-telegram       — Link employee to Telegram ID
```

These are authenticated via `X-Bot-Key` header. Verify they all work and return clean JSON.

## Step 3: Verify Jake-critical endpoints return useful data

Jake will primarily call these endpoints. Test each one with:
```bash
curl -H "X-Bot-Key: YOUR_BOT_API_KEY" https://ops-ai-production.up.railway.app/api/v1/ENDPOINT
```

### Must work:
- `GET /api/v1/trucks` — Jake asks "how many trucks do we have?"
- `GET /api/v1/trips` — Jake asks "how many trips this week?"
- `GET /api/v1/kpis/summary` — Jake asks "give me the weekly summary"
- `GET /api/v1/kpis/by-truck` — Jake asks "which truck has the most trips?"
- `GET /api/v1/reports/daily-summary` — Jake asks "what happened today?"
- `GET /api/v1/reports/fuel-efficiency` — Jake asks "what's our fuel cost?"
- `GET /api/v1/reports/anomalies` — Jake asks "any issues flagged?"
- `GET /api/v1/bot/pending-approvals` — Jake asks "anything pending?"
- `GET /api/v1/bot/employees` — Jake asks "who's on the team?"
- `GET /api/v1/attendance` — Jake asks "who showed up today?"

### Check for each:
1. Does it require auth? (should accept X-Bot-Key OR JWT)
2. Does it return clean JSON?
3. Are date filters supported? (Jake will pass ?start_date=&end_date=)
4. What happens when there's no data? (should return empty list, not 500)

## Step 4: Add X-Bot-Key auth to non-bot endpoints

Currently the `/api/v1/bot/*` endpoints use X-Bot-Key auth. But Jake also needs to call regular endpoints like `/api/v1/trucks`, `/api/v1/trips`, `/api/v1/kpis/summary`.

These regular endpoints currently require JWT auth (user login). We need to add X-Bot-Key as an alternative auth method so Jake can access them without a user session.

Create or update a dependency that accepts EITHER:
- Valid JWT token (for web dashboard users)
- Valid X-Bot-Key header (for Jake / external bots)

```python
async def get_current_user_or_bot(
    # Try JWT first, fall back to X-Bot-Key
    # If X-Bot-Key matches BOT_API_KEY, return a synthetic "bot user" 
    # with company_id from BOT_COMPANY_ID env var
):
```

Apply this to the endpoints Jake needs (listed above). Don't change endpoints Jake doesn't need.

## Step 5: Add a /api/v1/bot/status endpoint

Jake needs a simple health check to verify the OPS-AI connection is working:

```python
@router.get("/status")
async def bot_status():
    return {
        "status": "ok",
        "service": "ops-ai",
        "version": "...",
        "timestamp": datetime.utcnow().isoformat()
    }
```

This lets Jake's tool verify OPS-AI is reachable before making data queries.

## Step 6: Ensure attendance endpoint works for Jake

Jake will ask "who showed up today?" — the attendance endpoint needs to:
- Accept date filters: `GET /api/v1/attendance?date=2026-04-08`
- Return employee names + timestamps
- Work with X-Bot-Key auth

Check if this already works or needs adjustments.

## Step 7: Test everything

Run through this test script:
```bash
KEY="your-bot-api-key"
URL="https://ops-ai-production.up.railway.app"

# Health check
curl -s "$URL/api/v1/bot/status" -H "X-Bot-Key: $KEY" | python -m json.tool

# Trucks
curl -s "$URL/api/v1/trucks" -H "X-Bot-Key: $KEY" | python -m json.tool

# Trips (this week)
curl -s "$URL/api/v1/trips?start_date=2026-04-06&end_date=2026-04-12" -H "X-Bot-Key: $KEY" | python -m json.tool

# KPIs
curl -s "$URL/api/v1/kpis/summary" -H "X-Bot-Key: $KEY" | python -m json.tool

# Daily report
curl -s "$URL/api/v1/reports/daily-summary" -H "X-Bot-Key: $KEY" | python -m json.tool

# Pending approvals
curl -s "$URL/api/v1/bot/pending-approvals" -H "X-Bot-Key: $KEY" | python -m json.tool

# Employees
curl -s "$URL/api/v1/bot/employees" -H "X-Bot-Key: $KEY" | python -m json.tool
```

Every endpoint should return valid JSON (even if data is empty).

## Step 8: Commit

```bash
git add -A && git commit -m "Phase C: Harden bot API endpoints for Jake (OpenClaw) access" && git push
```

---

## Important notes

- DO NOT change how n8n worker bots authenticate — they use the same X-Bot-Key and must keep working
- DO NOT add any OpenClaw-specific code to OPS-AI — OPS-AI should not know about OpenClaw
- DO NOT expose write endpoints to X-Bot-Key auth — Jake only READS
- The goal is: OPS-AI exposes clean, well-authenticated READ endpoints. Who calls them (Jake, n8n, future apps) is not OPS-AI's concern.
- OPS-AI must work perfectly fine if OpenClaw doesn't exist — it's a standalone system
