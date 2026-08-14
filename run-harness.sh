#!/usr/bin/env bash
cd /home/brun3y/IBM_Bob_Harness

# cargar variables del .env
set -a
. ./.env
set +a

export PATH="/home/brun3y/.local/bin:/usr/local/bin:/usr/bin:/bin"
export HARNESS_URL="${HARNESS_URL:-http://localhost:8080}"

# aceptar la licencia de Bob una vez (idempotente)
bob --accept-license -p "print: ready" >/dev/null 2>&1 || true

cd api
# API REST
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080 &
API_PID=$!

# esperar a que /health responda
for i in $(seq 1 30); do
  curl -fsS http://localhost:8080/health >/dev/null 2>&1 && break
  sleep 1
done

# bot de Slack
python3 slack_bot.py &
BOT_PID=$!

# si cualquiera muere, terminar (systemd reinicia todo)
wait -n
kill "$API_PID" "$BOT_PID" 2>/dev/null || true
