#!/usr/bin/env bash
# Cron wrapper for sync_local.py - cron doesn't source shell env files
# by itself, so this does it explicitly before running. See
# ../README.md "Running on a schedule".
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${FASTMAIL_SYNC_ENV_FILE:-$REPO_DIR/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "cron_sync: missing env file $ENV_FILE" >&2
    exit 1
fi
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/scripts/sync_local.py"
