#!/usr/bin/env bash
#
# One-shot host setup for running the Bob Harness directly (no container).
# Run this ON the VM, from the repo root, after cloning:
#
#   git clone https://github.com/BrUn3y/IBM_Bob_Harness.git
#   cd IBM_Bob_Harness
#   ./deploy/setup-vm.sh
#
# Installs: a 2 GB swapfile, base packages, Node.js 22, Bob Shell, Python deps.
set -euo pipefail

BOB_VERSION="${BOB_VERSION:-1.0.5}"
BOB_TARBALL="https://s3.us-south.cloud-object-storage.appdomain.cloud/bob-shell/bobshell-${BOB_VERSION}.tgz"

# Run from the repo root regardless of where the script was invoked from.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

echo "==> Adding a 2 GB swapfile (memory cushion for 1 GB VMs)"
if ! swapon --show | grep -q '/swapfile'; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
else
  echo "    (swapfile already present, skipping)"
fi

echo "==> Installing base packages"
sudo apt-get update
sudo apt-get install -y git curl python3 python3-pip cron
sudo systemctl enable --now cron   # needed for scheduled tasks

echo "==> Installing Node.js 22 (Bob is a Node app)"
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
else
  echo "    (Node >= 22 already present: $(node -v))"
fi

echo "==> Installing Bob Shell ${BOB_VERSION}"
sudo npm install -g "$BOB_TARBALL"

echo "==> Installing Python dependencies (per-user)"
pip3 install --user --break-system-packages -r api/requirements.txt

echo
echo "==> Installed versions:"
node --version
bob --version
python3 -m uvicorn --version

cat <<EOF

Runtime ready. Next:
  cp .env.example .env
  nano .env                    # fill in your API key + Slack tokens
  ./deploy/configure-env.sh    # adjust paths for a direct run
  ./deploy/install-service.sh  # start the always-on service
EOF
