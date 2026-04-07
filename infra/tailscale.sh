#!/bin/bash
# ================================================================
# openclaw-stack — Tailscale install
# Creates private 100.x.x.x network between:
#   - Hetzner (FastAPI + n8n + DB)
#   - DO Singapore $6 (OpenClaw gateway)
#   - DO Singapore $24 (Ollama inference)
#   - Your local machine / phone
#
# Usage: bash infra/tailscale.sh
# After install: tailscale up --authkey=<your-auth-key>
# Get auth key: https://login.tailscale.com/admin/settings/keys
# ================================================================

set -euo pipefail

echo "==> Installing Tailscale..."

if command -v tailscale &> /dev/null; then
    echo "    Tailscale already installed."
    tailscale version
else
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl enable tailscaled
    systemctl start tailscaled
    echo "    Tailscale installed."
fi

echo ""
echo "==> Tailscale setup complete."
echo ""
echo "To connect this machine to your Tailnet:"
echo "  tailscale up --authkey=<your-auth-key>"
echo ""
echo "Get your auth key at: https://login.tailscale.com/admin/settings/keys"
echo "  - Use a reusable key for servers"
echo "  - Use an ephemeral key for short-lived containers"
echo ""
echo "After connecting, your Tailscale IP will appear at:"
echo "  tailscale ip -4"
echo ""
echo "─── How this stack uses Tailscale ─────────────────────────"
echo ""
echo "  Hetzner (this server)"
echo "    FastAPI:    100.x.x.1:8000   (internal)"
echo "    n8n:        100.x.x.1:5678   (internal)"
echo "    PostgreSQL: 100.x.x.1:5432   (internal)"
echo ""
echo "  DO SG \$6 — OpenClaw gateway"
echo "    Gateway:    100.x.x.2:18789  (internal, NEVER public)"
echo ""
echo "  DO SG \$24 — Ollama inference"
echo "    Ollama:     100.x.x.3:11434  (internal)"
echo ""
echo "  n8n calls FastAPI via Tailscale IP, not public internet."
echo "  OpenClaw gateway accessible from Hetzner FastAPI via Tailscale."
echo "  Ollama accessible from FastAPI model router via Tailscale."
echo "────────────────────────────────────────────────────────────"
