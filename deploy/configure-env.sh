#!/usr/bin/env bash
#
# Adjust .env for a direct (non-container) run. Run ON the VM from the repo root
# AFTER creating .env with your secrets (cp .env.example .env && nano .env).
#
# What it changes vs the container defaults:
#   * BOB_WORKDIR / SLACK_WORKDIR -> the repo dir, so Bob finds .bob/ (the
#     unrestricted-dev custom mode). In the container these are "/" because the
#     config is copied to /.bob; here the config lives in the repo.
#   * BOB_SCHEDULES_FILE / BOB_CRON_LOG -> ./workspace (the container used the
#     mounted /workspace volume, which doesn't exist on the host).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Run: cp .env.example .env && nano .env" >&2
  exit 1
fi

# Point Bob's working directory at the repo (so it can find .bob/).
sed -i "s#^BOB_WORKDIR=.*#BOB_WORKDIR=$REPO#" .env

# Append the vars that aren't in .env.example, only if missing.
grep -q '^SLACK_WORKDIR='      .env || echo "SLACK_WORKDIR=$REPO"                               >> .env
grep -q '^BOB_SCHEDULES_FILE=' .env || echo "BOB_SCHEDULES_FILE=$REPO/workspace/schedules.json" >> .env
grep -q '^BOB_CRON_LOG='       .env || echo "BOB_CRON_LOG=$REPO/workspace/cron.log"             >> .env

mkdir -p "$REPO/workspace"

echo "==> .env configured for a direct run. Review it (secrets hidden):"
sed -E 's/^(BOBSHELL_API_KEY|SLACK_BOT_TOKEN|SLACK_APP_TOKEN)=.*/\1=***HIDDEN***/' .env \
  | grep -vE '^\s*#|^\s*$'
echo
echo "Next: ./deploy/install-service.sh"
