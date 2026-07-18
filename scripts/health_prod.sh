#!/usr/bin/env bash
# Прод health-check + алерты (webhook / Telegram / logs/alerts.jsonl)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
mkdir -p logs

explainlaw health --alert
