#!/bin/bash
# ================================================================
# openclaw-stack — UFW firewall rules
# Called by setup.sh or run standalone to reset firewall rules
# Usage: bash infra/ufw-rules.sh
# ================================================================

set -euo pipefail

echo "==> Applying UFW firewall rules..."

# Install UFW if missing
apt-get install -y ufw -q

# Reset to clean state
ufw --force reset

# Default policy — deny all inbound, allow all outbound
ufw default deny incoming
ufw default allow outgoing

# ─── Allowed inbound ports ───────────────────────────────────────

# SSH — always first so you don't lock yourself out
ufw allow 22/tcp comment 'SSH'

# HTTP + HTTPS — for Cloudflare Tunnel and any web services
ufw allow 80/tcp  comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

# ─── Explicitly blocked ports ────────────────────────────────────

# OpenClaw gateway — NEVER expose publicly
# Access only via Tailscale (100.x.x.x) or Cloudflare Tunnel
ufw deny 18789/tcp comment 'OpenClaw gateway — internal only'

# FastAPI direct — also internal only, proxied via Cloudflare Tunnel
ufw deny 8000/tcp comment 'FastAPI — internal only'

# PostgreSQL — internal only
ufw deny 5432/tcp comment 'PostgreSQL — internal only'

# Redis — internal only
ufw deny 6379/tcp comment 'Redis — internal only'

# Ollama — internal only
ufw deny 11434/tcp comment 'Ollama — internal only'

# ─── Tailscale interface (allow all traffic on tailscale0) ───────
# Tailscale creates a private 100.x.x.x network between your devices
# Services that need internal-only access communicate over this interface
ufw allow in on tailscale0 comment 'Tailscale private network'

# ─── Enable ──────────────────────────────────────────────────────
ufw --force enable

echo ""
ufw status verbose
echo ""
echo "==> UFW rules applied."
echo ""
echo "IMPORTANT: Port 18789 (OpenClaw) is blocked publicly."
echo "Access OpenClaw only via Tailscale (100.x.x.x) or Cloudflare Tunnel."
