#!/usr/bin/env bash
# Разовый/периодический бэкфилл: дельты поправок → гейты → missing acts (§8.3, §11)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

LIMIT="${LIMIT:-}"
LIMIT_ARG=""
if [ -n "$LIMIT" ]; then
  LIMIT_ARG="--limit $LIMIT"
fi

docker compose --profile local up -d
python scripts/init_infra.py

echo "[backfill] rebuild-deltas $LIMIT_ARG"
explainlaw rebuild-deltas $LIMIT_ARG

echo "[backfill] fetch-missing"
explainlaw fetch-missing --limit "${FETCH_MISSING_LIMIT:-20}"

echo "[backfill] status"
explainlaw status
