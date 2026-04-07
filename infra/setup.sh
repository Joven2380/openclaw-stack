#!/bin/bash
# ================================================================
# openclaw-stack — Hetzner server bootstrap
# Run once on a fresh Ubuntu 24.04 VPS as root
# Usage: bash infra/setup.sh
# ================================================================

set -euo pipefail

echo "==> openclaw-stack server setup starting..."

# ─── System update ───────────────────────────────────────────────
echo "==> Updating system packages..."
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    curl \
    wget \
    git \
    nano \
    htop \
    unzip \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common \
    build-essential \
    libpq-dev

# ─── Swap (important for CX21 — 4GB RAM, helps with Ollama) ──────
echo "==> Configuring 4GB swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "vm.swappiness=10" >> /etc/sysctl.conf
    sysctl -p
    echo "    Swap created."
else
    echo "    Swap already exists, skipping."
fi

# ─── Docker ──────────────────────────────────────────────────────
echo "==> Installing Docker..."
if ! command -v docker &> /dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
        https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -y
    apt-get install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "    Docker installed."
else
    echo "    Docker already installed, skipping."
fi

# ─── Non-root docker user (optional — if deploying as non-root) ──
# Uncomment if you create a deploy user:
# usermod -aG docker deployer

# ─── UFW firewall ────────────────────────────────────────────────
echo "==> Configuring UFW firewall..."
bash "$(dirname "$0")/ufw-rules.sh"

# ─── Tailscale ───────────────────────────────────────────────────
echo "==> Installing Tailscale..."
bash "$(dirname "$0")/tailscale.sh"

# ─── Clone repo ──────────────────────────────────────────────────
echo ""
echo "==> Server setup complete."
echo ""
echo "Next steps:"
echo "  1. cd /opt && git clone https://github.com/Joven2380/openclaw-stack.git"
echo "  2. cd openclaw-stack && cp .env.example .env && nano .env"
echo "  3. docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "Tailscale auth (if not done): tailscale up --authkey=<your-auth-key>"
