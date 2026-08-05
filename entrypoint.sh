#!/usr/bin/env bash
# Container entrypoint. Verifies the environment, then serves the REST API
# (default), the Slack bot, both together (serve-all), or the `bob` CLI.
set -euo pipefail

# Ensure bob is reachable even in a non-login shell.
export PATH="/root/.local/bin:/root/.bob/bin:/usr/local/bin:/usr/bin:${PATH}"

if [ -z "${BOBSHELL_API_KEY:-}" ]; then
  echo "ERROR: BOBSHELL_API_KEY is not set." >&2
  echo "       Pass it with:  docker run --env-file .env ...  (or -e BOBSHELL_API_KEY=...)" >&2
  exit 1
fi

if ! command -v bob >/dev/null 2>&1; then
  echo "ERROR: 'bob' not found on PATH after install." >&2
  echo "       PATH=$PATH" >&2
  exit 1
fi

# Accept the IBM license once, non-interactively (idempotent).
bob --accept-license -p "print: ready" >/dev/null 2>&1 || true

# Start the cron daemon that fires scheduled runs. The API regenerates root's
# crontab from the persisted registry (/workspace/schedules.json) on startup;
# cron just needs to be running to pick it up. Safe to start even with no
# schedules yet. `cron` daemonizes on its own.
start_cron() {
  if command -v cron >/dev/null 2>&1; then
    cron && echo "Bob harness: cron daemon started (scheduler enabled)"
  else
    echo "WARNING: 'cron' not found; scheduled runs will not fire." >&2
  fi
}

case "${1:-serve}" in
  serve)
    echo "Bob harness: starting REST API on 0.0.0.0:8080 (mode=${BOB_MODE:-unrestricted-dev})"
    start_cron
    cd /app
    exec uvicorn server:app --host 0.0.0.0 --port 8080
    ;;
  serve-all)
    # Single-container mode: run the REST API AND (optionally) the Slack bot.
    # The bot is only started when SLACK_BOT_TOKEN and SLACK_APP_TOKEN are set.
    # If either token is absent, we fall back to API-only mode so the container
    # starts successfully without Slack credentials.
    if [ -n "${SLACK_BOT_TOKEN:-}" ] && [ -n "${SLACK_APP_TOKEN:-}" ]; then
      SLACK_ENABLED=true
      echo "Bob harness: starting REST API + Slack bot in one container"
    else
      SLACK_ENABLED=false
      echo "Bob harness: SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — starting REST API only (Slack bot disabled)"
    fi
    start_cron
    cd /app
    uvicorn server:app --host 0.0.0.0 --port 8080 &
    api=$!
    if [ "$SLACK_ENABLED" = true ]; then
      # Wait for the API to answer before starting the bot (avoids early errors).
      for _ in $(seq 1 30); do
        curl -fsS http://localhost:8080/health >/dev/null 2>&1 && break
        sleep 0.5
      done
      HARNESS_URL="${HARNESS_URL:-http://localhost:8080}" python3 slack_bot.py &
      bot=$!
      wait -n "$api" "$bot"
      ec=$?
      kill "$api" "$bot" 2>/dev/null || true
      exit "$ec"
    else
      wait "$api"
      exit $?
    fi
    ;;
  slack)
    # Bidirectional Slack bot (Socket Mode). Talks to the REST API over HTTP,
    # so it needs HARNESS_URL + the SLACK_* tokens (see .env / docker-compose).
    echo "Bob harness: starting Slack bot (harness=${HARNESS_URL:-http://localhost:8080})"
    cd /app
    exec python3 slack_bot.py
    ;;
  shell)
    # Interactive bob session:  docker run -it bob-harness shell
    shift
    exec bob "$@"
    ;;
  bob)
    # Direct bob CLI passthrough:  docker run bob-harness bob -p "..." --yolo
    shift
    exec bob "$@"
    ;;
  *)
    # Anything else is executed verbatim (e.g. `bash`).
    exec "$@"
    ;;
esac
