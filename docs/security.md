# Security hardening checklist

This document covers the security posture of the openclaw-stack.
Complete every item before accepting any client work or exposing any service.

---

## Server provisioning (Hetzner)

- [ ] Run `bash infra/setup.sh` on fresh Ubuntu 24.04
- [ ] Run `bash infra/ufw-rules.sh` — verify port 18789 is DENIED
- [ ] Run `bash infra/tailscale.sh` and connect all 3 servers to Tailnet
- [ ] Disable root SSH login: set `PermitRootLogin no` in `/etc/ssh/sshd_config`
- [ ] Disable password SSH: set `PasswordAuthentication no`, use SSH keys only
- [ ] Add your SSH public key to `~/.ssh/authorized_keys` before disabling passwords
- [ ] Set `POSTGRES_PASSWORD` in `.env` to a strong random value (not "postgres")
- [ ] Set `REDIS_PASSWORD` in `.env` — blank Redis has no auth in prod
- [ ] Verify all ports: `ufw status verbose`

```bash
# Verify OpenClaw port is blocked
nc -zv localhost 18789   # should fail/timeout
```

---

## OpenClaw — CVE-2026-25253 (CVSS 8.8)

**Status:** Patched in v2026.1.29. Always run latest.

**What it was:** The Control UI accepted a `gatewayUrl` query parameter and
auto-connected over WebSocket, leaking the auth token to attacker-controlled servers.
One malicious link = full RCE on the host machine.

**Mandatory mitigations:**

- [ ] Always run OpenClaw >= v2026.1.29
- [ ] Set `bind: "127.0.0.1"` in `~/openclaw/config.yaml` — NEVER `0.0.0.0`
- [ ] Keep `exec.approvals: on` — never disable confirmation prompts
- [ ] Set `sandbox: strict` — never `loose`
- [ ] Block port 18789 via UFW (done in `ufw-rules.sh`)
- [ ] Access OpenClaw Control UI only via Tailscale — never open browser to it
  on a machine that also visits untrusted sites
- [ ] Rotate `OPENCLAW_AUTH_TOKEN` immediately if you suspect compromise
- [ ] Audit ClawHub skills — only install from sources you've reviewed
- [ ] After update, rotate all auth tokens: `openclaw auth rotate`

```yaml
# ~/openclaw/config.yaml — required settings
bind: "127.0.0.1"
port: 18789
sandbox: strict
exec:
  approvals: on
```

---

## Secrets management

- [ ] `.env` is in `.gitignore` — verify with `git status` before every commit
- [ ] `config/clients/` is in `.gitignore` — client configs never go to GitHub
- [ ] All API keys rotated if accidentally committed (check `git log -p`)
- [ ] `JWT_SECRET` is a 64-char random hex: `openssl rand -hex 32`
- [ ] `ADMIN_API_KEY` is a 64-char random hex: `openssl rand -hex 32`
- [ ] `SECRET_KEY` is a 64-char random hex: `openssl rand -hex 32`
- [ ] No hardcoded credentials anywhere in `api/` — use `settings.field` pattern

---

## Network

- [ ] All inter-service communication goes over Tailscale (100.x.x.x), not public IPs
- [ ] FastAPI bound to `127.0.0.1:8000` in prod (see `docker-compose.prod.yml`)
- [ ] PostgreSQL bound to `127.0.0.1:5432` in prod
- [ ] Redis bound to `127.0.0.1:6379` in prod
- [ ] Cloudflare Tunnel used for any public-facing endpoints — no direct port exposure
- [ ] Ollama on DO droplet: `OLLAMA_HOST=127.0.0.1` — access via Tailscale only

---

## Telegram bots

- [ ] Webhook secret set (`TELEGRAM_WEBHOOK_SECRET`) — prevents spoofed updates
- [ ] Validate `X-Telegram-Bot-Api-Secret-Token` header on every incoming webhook
- [ ] `TELEGRAM_ALERT_CHAT_ID` is your personal chat only — never a group
- [ ] Bot tokens stored only in `.env` — never in n8n plaintext, always via env var

---

## Client isolation

- [ ] Each client has a unique `api_key_hash` in the `clients` table
- [ ] All agent memory queries include `client_id` filter — no cross-client leakage
- [ ] Client configs live in `config/clients/{client_id}/` — gitignored
- [ ] Per-client daily budget enforced in middleware before every API call
- [ ] Client API keys shown only once at creation — only hash stored in DB

---

## Monitoring

- [ ] Error alerts wired to `TELEGRAM_ALERT_CHAT_ID` via `api/core/alerts.py`
- [ ] n8n error trigger workflow active — any workflow failure pings Telegram
- [ ] Weekly cost report running (n8n Sunday 9AM cron)
- [ ] Log rotation configured in `docker-compose.prod.yml` (10MB max, 3 files)

---

## Incident response

If you suspect a breach:

1. Immediately rotate all API keys: Anthropic, OpenAI, Qwen, Telegram, Supabase
2. Rotate `JWT_SECRET`, `ADMIN_API_KEY`, `SECRET_KEY` in `.env`
3. Restart all containers: `docker compose down && docker compose up -d`
4. Run `openclaw auth rotate` if OpenClaw was involved
5. Check `task_logs` table for unusual `client_id` or high token usage
6. Review `ufw` logs: `grep "UFW BLOCK" /var/log/ufw.log`
7. Check Docker logs: `docker logs openclaw_api --since 24h`
