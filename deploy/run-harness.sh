#!/usr/bin/env bash
#
# Starts the REST API + Slack bot together — the direct-Python equivalent of the
# container's `serve-all` entrypoint. Invoked by the bob-harness systemd unit;
# not usually run by hand.
#
# If either process dies, the script exits so systemd restarts the whole unit.

# Resolve the repo root as the parent of this script's directory (deploy/..).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Load .env (export every variable so the child processes inherit them).
set -a
[ -f .env ] && . ./.env
set +a

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HARNESS_URL="${HARNESS_URL:-http://localhost:8080}"

# Accept Bob's license once (idempotent). Runs at the repo root so Bob can see
# .bob/ (the unrestricted-dev custom mode); harmless if already accepted.
bob --accept-license -p "print: ready" >/dev/null 2>&1 || true

cd api

# REST API.
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080 &
API_PID=$!

# Wait for the API to answer before starting the bot (bot talks to it locally).
for _ in $(seq 1 30); do
  curl -fsS http://localhost:8080/health >/dev/null 2>&1 && break
  sleep 1
done

# Slack bot (Socket Mode).
python3 slack_bot.py &
BOT_PID=$!

# Exit as soon as either child exits; systemd (Restart=always) brings it back.
wait -n
kill "$API_PID" "$BOT_PID" 2>/dev/null || true
