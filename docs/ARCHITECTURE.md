# SYSTEM ARCHITECTURE — The Full Picture
# Last updated: April 8, 2026
# Author: Job Pangilinan + Claude (context partner)

---

## What we're building

Three strictly separated systems that work together:

1. **Jake (OpenClaw)** — Premium AI overseer on Hetzner
2. **OPS-AI** — Business ERP + fleet management on Railway  
3. **n8n Worker Bots** — Cheap automation bots on Railway

---

## System 1: Jake / OpenClaw (Hetzner)

**Server:** 5.223.94.137 (bottleneck-ai.com)  
**Stack:** FastAPI + asyncpg + Caddy + Redis  
**Repo:** github.com/Joven2380/openclaw-stack  
**Model:** Claude Sonnet 4.6 (Anthropic API)  
**Purpose:** Job's personal AI executive assistant

**What Jake does:**
- Personal AI right hand for Job across ALL projects (RPQ, JM-TECH, Bottleneck)
- Reads OPS-AI data via API (trips, trucks, fuel, KPIs, attendance)
- Triggers n8n workflows via webhooks
- Remembers past conversations (pgvector memory)
- Tracks token costs
- Accessible via Telegram

**What Jake does NOT do:**
- Replace the OPS-AI worker bots
- Handle high-volume repetitive tasks (that's what n8n bots do cheaply)
- Store business data (OPS-AI Postgres is the source of truth)

**Key files:**
- `api/core/agent_runner.py` — Main engine with tool execution loop
- `api/tools/registry.py` — Tool handlers + Anthropic schemas (TOOL_SCHEMAS)
- `api/core/model_clients.py` — Provider dispatch (Anthropic, OpenAI, Qwen, Ollama)
- `agents/jake.yaml` — Jake's persona, model, tools list
- `agents/SOUL.md` — Shared rules across all agents

**Current tools (registry.py):**
- `query_fleet` — Currently queries local empty tables. NEEDS REWIRING to OPS-AI API.
- `query_trips` — Same. NEEDS REWIRING.
- `query_fuel` — Same. NEEDS REWIRING.
- `escalate` — Routes to other agents. Works.
- `send_telegram` — Sends Telegram messages. Works.
- `classify_intent` — Routes to Clay for classification. Works.
- `trigger_n8n_webhook` — Stub. NEEDS WIRING to real n8n webhook URLs.

**Agents configured (only Jake is active):**
- jake (Claude Sonnet) — ACTIVE
- dame (GPT-4o) — DISABLED
- kobe (Ollama/Qwen) — DISABLED  
- sam — DISABLED
- king — DISABLED

---

## System 2: OPS-AI (Railway)

**URL:** ops-ai-production.up.railway.app (API)  
**Web:** web-production-11623.up.railway.app (Dashboard)  
**Stack:** FastAPI + SQLAlchemy + Alembic + Railway Postgres  
**Repo:** github.com/Joven2380/ops-ai  
**Purpose:** Fleet management ERP for RPQ Truckwide Corp

**Modules:**
- Trips (CRUD, import, export, OCR scan)
- Trucks (fleet registry, configurations)
- Drivers + Employees (profiles, rates, Telegram linking)
- Fuel (receipts, VAT fields, import)
- Expenses (preview, import, BIR fields)
- Attendance (biometric, bot-based photo logging)
- Payroll (periods, compute, lock, records)
- Tires (tracking, replacement)
- Maintenance (work orders)
- Procurement (purchase orders, approval flow)
- Inventory (stock, movements, truck assignments)
- Documents (vault, templates, generation)
- Billing (engine, export, client rates)
- KPIs (summary, by-truck, by-driver)
- Reports (daily summary, weekly, fuel efficiency, anomalies)
- Intelligence feed (business insights)
- Fleet calculator (density, truck configs, compute)
- OCR pipeline (Claude Vision, Gemini, Tesseract engines)
- AI Analyst (multi-agent, SSE streaming)
- Bot API (receipt upload, attendance, query, link-telegram)

**Key API endpoints Jake should call:**
```
GET  /api/v1/trips                    — Trip list with filters
GET  /api/v1/trucks                   — Fleet registry
GET  /api/v1/kpis/summary             — Weekly KPI dashboard data
GET  /api/v1/kpis/by-truck            — Per-truck performance
GET  /api/v1/kpis/by-driver           — Per-driver performance
GET  /api/v1/reports/daily-summary     — Today's operations summary
GET  /api/v1/reports/weekly-summary    — Week overview
GET  /api/v1/reports/fuel-efficiency   — Fuel consumption analysis
GET  /api/v1/reports/anomalies         — Flagged issues
GET  /api/v1/attendance               — Attendance records
GET  /api/v1/billing/summary           — Revenue/billing data
GET  /api/v1/bot/pending-approvals     — Receipts awaiting review
GET  /api/v1/bot/employees             — Employee list
POST /api/v1/bot/query                 — AI analyst query
```

**Auth for bot/external access:**
- Header: `X-Bot-Key: <BOT_API_KEY>`
- The BOT_API_KEY is set in Railway env vars
- Jake needs this key stored in OpenClaw's .env as `OPSAI_API_KEY`

**Database:** Railway Postgres (36 migrations, real RPQ data)
- This is the SOURCE OF TRUTH for all business data
- OpenClaw should NEVER duplicate this data — only read via API

---

## System 3: n8n Worker Bots (Railway)

**URL:** n8n-production-3eb7.up.railway.app  
**Stack:** n8n Community Edition, connected to Railway Postgres  
**Purpose:** Cheap automation for repetitive tasks

**Workflows:**
1. `01-receipt-upload.json` — Photo → OCR → log receipt
2. `02-attendance.json` — Photo → employee select → log attendance  
3. `03-purchasing-query.json` — `?` prefix → AI query → response
4. `04-manager-alerts.json` — Every 30min → check pending → alert manager
5. `05-daily-digest.json` — 7AM daily → morning summary → send to owner
6. `06-start-command.json` — Bot /start handler

**Model strategy for worker bots:**
- Gemini free tier (primary for simple tasks)
- ChatGPT subscription API (for medium complexity)
- Minimal token usage — most logic is in n8n nodes, not AI

**n8n webhook URLs Jake can trigger:**
- These need to be discovered from n8n and added to OpenClaw's .env
- Jake's `trigger_n8n_webhook` tool will POST to these URLs

---

## The Bridge: How Jake connects to OPS-AI

```
Job (Telegram)
    │
    ▼
Jake (OpenClaw / Hetzner)
    │
    ├── READS from OPS-AI API (GET requests with X-Bot-Key auth)
    │     → /api/v1/trips, /trucks, /kpis/summary, etc.
    │
    ├── TRIGGERS n8n workflows (POST to webhook URLs)  
    │     → daily digest, attendance check, etc.
    │
    └── STORES in local Postgres (agent memory + cost logs only)
```

**Environment variables needed in OpenClaw .env:**
```
OPSAI_API_URL=https://ops-ai-production.up.railway.app
OPSAI_API_KEY=<BOT_API_KEY from Railway>
N8N_BASE_URL=https://n8n-production-3eb7.up.railway.app
N8N_WEBHOOK_DAILY_DIGEST=<webhook-id>
N8N_WEBHOOK_ATTENDANCE=<webhook-id>
N8N_WEBHOOK_RECEIPT=<webhook-id>
N8N_WEBHOOK_MANAGER_ALERTS=<webhook-id>
```

---

## Build order (what to do next)

### Phase A: Wire Jake to OPS-AI (OpenClaw side)
1. Add OPSAI env vars to OpenClaw .env on Hetzner
2. Rewrite registry.py tools to call OPS-AI API instead of local tables
3. Add new tools: get_kpi_summary, get_daily_report, get_attendance
4. Test: ask Jake "how many trips this week?" and verify he calls OPS-AI

### Phase B: Wire Jake to n8n (OpenClaw side)
5. Get n8n webhook URLs from the n8n dashboard
6. Add webhook URLs to OpenClaw .env
7. Wire trigger_n8n_webhook tool to real URLs
8. Test: tell Jake "run the daily digest" and verify n8n fires

### Phase C: OPS-AI bot endpoint hardening (OPS-AI side)
9. Ensure /api/v1/bot/* endpoints return clean JSON for Jake
10. Add any missing endpoints Jake needs (e.g. /api/v1/billing/summary)
11. Test: verify all endpoints return data with X-Bot-Key auth

### Phase D: Jake's personality + SOUL.md tuning
12. Update SOUL.md with Jake's overseer role definition
13. Update jake.yaml with expanded tools list
14. Add Taglish response patterns for operational queries
15. Test: natural conversation flow via Telegram

---

## Cost strategy

| System | Model | Cost | Volume |
|--------|-------|------|--------|
| Jake | Claude Sonnet 4.6 | ~$3/15 per 1M tokens | Low (5-20 queries/day) |
| OPS-AI AI Analyst | Gemini Flash (free) | $0 | Medium |
| n8n worker bots | GPT via ChatGPT sub / Gemini | ~$0 | High volume, tiny prompts |
| OpenClaw memory | OpenAI embeddings | ~$0.02/1M tokens | Minimal |

**Monthly estimate:** $5-15 for Jake, ~$0 for everything else.

---

## File locations

| What | Where |
|------|-------|
| This document | Both repos: `docs/ARCHITECTURE.md` |
| OpenClaw code | `C:/Users/joven/openclaw-stack/` |
| OPS-AI code | `C:/Users/joven/ops-ai/` |
| OpenClaw server | `ssh root@5.223.94.137` → `/root/openclaw-stack/` |
| OPS-AI server | Railway (auto-deploy from GitHub) |
| n8n workflows | `ops-ai/n8n/workflows/*.json` |
