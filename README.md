# openclaw-stack

Multi-agent AI automation OS for **RPQ Truckwide Corp** and freelance agency work.

Owner: **Job Pangilinan** — GitHub: [@Joven2380](https://github.com/Joven2380)

---

## What It Is

A self-hosted, multi-model AI agent platform that routes tasks across 6 operational use cases:

| # | Use Case | Description |
|---|----------|-------------|
| 1 | **AI Agents for Clients** | Deploy branded agents per client via Telegram/FB/WhatsApp |
| 2 | **OPS-AI Fleet Ops** | Trucking ops: trips, fuel, payroll, billing, expense analysis |
| 3 | **Website & SaaS Builds** | Code generation, PR review, spec-to-scaffold automation |
| 4 | **Personal Automation** | Calendar, email triage, reminders, file ops via Telegram |
| 5 | **n8n + OpenClaw Dev** | Internal workflow automation, webhook orchestration |
| 6 | **Marketing & Sales** | Caption writing, lead tracking, content scheduling |

---

## Architecture

```
Telegram / WhatsApp / Facebook Messenger
           │
           ▼
    n8n (Railway)           ← webhook orchestration, routing rules
           │
           ▼
  FastAPI OpenClaw Core     ← Hetzner VPS, port 18789 (never public)
  (api/main.py)             ← agent dispatch, cost tracking, memory
           │
           ▼
    Model Router            ← selects model by task type + cost budget
     ├── Claude Sonnet 4.6  (Anthropic API)     ← reasoning, complex tasks
     ├── GPT-4o             (OpenAI API)         ← multimodal, fallback
     ├── Qwen3-30B-A3B      (Qwen API / remote)  ← mid-tier, cost-efficient
     ├── Qwen3:8b           (Ollama, local)       ← fast, free, simple tasks
     └── QwQ-32B            (Qwen API / remote)  ← deep reasoning
           │
           ▼
  Supabase (pgvector)       ← agent memory, embeddings, client configs
  Redis                     ← session state, rate limits, cost counters
```

---

## Repo Structure

```
openclaw-stack/
├── api/                        # FastAPI core application
│   ├── main.py                 # App entry point
│   ├── routers/                # Route handlers (agents, webhooks, admin)
│   ├── models/                 # SQLAlchemy models
│   ├── core/                   # Model router, cost tracker, config
│   ├── db/
│   │   └── migrations/         # SQL migration files (auto-run on DB init)
│   └── middleware/             # Auth, logging, rate limiting
├── agents/                     # Agent definitions (Nora, Max, Clay, etc.)
├── config/
│   └── clients/                # Per-client YAML configs (git-ignored)
├── workflows/                  # n8n workflow JSON exports
├── docs/                       # Architecture notes, runbooks
├── infra/                      # Nginx config, systemd units, deploy scripts
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Prerequisites

- Docker + Docker Compose v2
- Python 3.11+
- Git
- A Hetzner VPS (Ubuntu 24.04) with at least 4 vCPU / 8 GB RAM
- Cloudflare Tunnel or Tailscale (for secure external access)
- Supabase project (for pgvector memory)
- Telegram Bot Token (from @BotFather)

---

## Local Dev Setup

```bash
# 1. Clone
git clone https://github.com/Joven2380/openclaw-stack.git
cd openclaw-stack

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in your API keys

# 3. Start services (Postgres + pgvector, Redis, API)
docker compose up -d

# 4. (Optional) Run API outside Docker for hot-reload with IDE
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

API will be available at: `http://localhost:8000`  
Swagger docs: `http://localhost:8000/docs`

---

## Environment Variables

| Variable | Description | Where to Get It |
|----------|-------------|-----------------|
| `SECRET_KEY` | App signing secret | `openssl rand -hex 32` |
| `ADMIN_API_KEY` | Internal admin endpoints | Generate any strong token |
| `ANTHROPIC_API_KEY` | Claude models | console.anthropic.com |
| `OPENAI_API_KEY` | GPT-4o | platform.openai.com |
| `QWEN_API_KEY` | Qwen remote models | dashscope.aliyuncs.com |
| `GEMINI_API_KEY` | Gemini (optional) | aistudio.google.com |
| `OLLAMA_BASE_URL` | Local Ollama instance | `http://localhost:11434` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot | @BotFather on Telegram |
| `TELEGRAM_ALERT_CHAT_ID` | Your personal chat ID | @userinfobot |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook validation token | Generate random string |
| `FB_PAGE_ID` | Facebook page | Facebook Page settings |
| `FB_PAGE_ACCESS_TOKEN` | FB Graph API token | developers.facebook.com |
| `FB_VERIFY_TOKEN` | Webhook verify token | Set any string, use same in FB dashboard |
| `DATABASE_URL` | Postgres connection (sync) | Compose: `postgresql://postgres:postgres@localhost:5432/openclaw` |
| `DATABASE_URL_ASYNC` | Postgres (asyncpg) | Same but `postgresql+asyncpg://...` |
| `SUPABASE_URL` | Supabase project URL | app.supabase.com → Settings → API |
| `SUPABASE_KEY` | Service role key (not anon) | app.supabase.com → Settings → API |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `SMTP_HOST` | Email SMTP server | Your email provider |
| `SMTP_PORT` | SMTP port (usually 587) | Your email provider |
| `SMTP_USER` | SMTP username/email | Your email provider |
| `SMTP_PASSWORD` | SMTP password or app password | Your email provider |
| `EMAIL_FROM` | From address for emails | Your email address |
| `OPENCLAW_GATEWAY_URL` | OpenClaw internal URL | Always `http://127.0.0.1:18789` |
| `OPENCLAW_AUTH_TOKEN` | Gateway auth token | Generate strong token |
| `N8N_BASE_URL` | n8n instance URL | Your Railway n8n deployment |
| `N8N_API_KEY` | n8n REST API key | n8n Settings → API |
| `JWT_SECRET` | JWT signing key | `openssl rand -hex 32` |
| `DEFAULT_DAILY_BUDGET_USD` | Per-agent daily spend cap | Set based on your budget |
| `GLOBAL_DAILY_BUDGET_USD` | Total daily spend cap | Set based on your budget |

---

## Deployment (Hetzner Ubuntu 24.04)

```bash
# On the VPS
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/Joven2380/openclaw-stack.git /opt/openclaw
cd /opt/openclaw
cp .env.example .env
nano .env  # fill in all keys

# Start
docker compose up -d

# Install systemd service for auto-restart
cp infra/openclaw.service /etc/systemd/system/
systemctl enable openclaw && systemctl start openclaw

# Check logs
docker compose logs -f api
```

---

## Security

> **CRITICAL: Port 18789 must NEVER be exposed to the public internet.**

- The OpenClaw Core API runs internally on port 18789
- External access is ONLY through **Cloudflare Tunnel** or **Tailscale**
- n8n on Railway calls OpenClaw via the Cloudflare Tunnel URL
- Telegram webhooks hit n8n first, never OpenClaw directly
- All secrets are in `.env` — never committed to git
- `config/clients/` is git-ignored — client configs stay local

```bash
# Recommended: Cloudflare Tunnel setup
cloudflared tunnel create openclaw
cloudflared tunnel route dns openclaw api.yourdomain.com
# Then set OPENCLAW_GATEWAY_URL in n8n to https://api.yourdomain.com
```

---

## Telegram Agent Commands

| Command | Agent | Description |
|---------|-------|-------------|
| `/nora` | Nora | RPQ fleet ops assistant — trips, fuel, payroll queries |
| `/max` | Max | Code & dev assistant — scaffolding, debugging, PR review |
| `/clay` | Clay | Client-facing agent dispatcher |
| `/ask` | Router | General Q&A, routes to best model by task |
| `/cost` | Admin | Show today's model spend vs. budget |
| `/status` | Admin | System health check — DB, Redis, model APIs |

---

## License

Private — RPQ Truckwide Corp / Job Pangilinan. Not for public distribution.
