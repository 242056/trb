#!/usr/bin/env bash
# Прод-ежедневный cron: collect → process → gate → fetch-missing [→ weekly publish]
# Не поднимает docker-compose (ожидает Yandex PG / Kafka / внешний MinIO).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -f .env ]; then
  echo "ERROR: .env не найден. Скопируйте .env.example и заполните Yandex/MinIO." >&2
  exit 1
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
mkdir -p logs

WEEKLY_ARGS=()
if [ "${1:-}" = "--weekly-publish" ]; then
  WEEKLY_ARGS=(--weekly-publish)
fi

explainlaw daily "${WEEKLY_ARGS[@]}"
explainlaw health --alert || true
