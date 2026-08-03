#!/usr/bin/env bash
#
# Install and start the bob-harness systemd service. Run ON the VM from the repo
# root, AFTER ./deploy/setup-vm.sh and after creating + configuring .env.
#
# Renders deploy/bob-harness.service for the current user and repo path, enables
# it at boot, and starts it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(whoami)"
UNIT=/etc/systemd/system/bob-harness.service

if [ ! -f "$REPO/.env" ]; then
  echo "ERROR: $REPO/.env not found. Create it first:" >&2
  echo "  cp .env.example .env && nano .env && ./deploy/configure-env.sh" >&2
  exit 1
fi

chmod +x "$REPO/deploy/run-harness.sh"

echo "==> Writing $UNIT (User=$USER_NAME, repo=$REPO)"
sed -e "s#__USER__#${USER_NAME}#g" -e "s#__REPO__#${REPO}#g" \
  "$REPO/deploy/bob-harness.service" | sudo tee "$UNIT" > /dev/null

echo "==> Enabling and starting the service"
sudo systemctl daemon-reload
sudo systemctl enable --now bob-harness

sleep 6
sudo systemctl --no-pager status bob-harness || true

cat <<EOF

If you see "Active: active (running)", verify with:
  curl -s http://localhost:8080/health; echo
  journalctl -u bob-harness -n 40 --no-pager   # look for "A new session has been established"

Then in Slack: /invite @Bob  (and message it — no @ needed).
EOF
