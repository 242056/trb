#!/usr/bin/env bash
# Ежедневный cron ExplainLaw (§7.1, §11)
# Пример crontab:
#   0 8 * * * /path/to/trb/scripts/daily.sh >> /var/log/explainlaw-daily.log 2>&1
#   0 9 * * 1 /path/to/trb/scripts/daily.sh --weekly-publish >> /var/log/explainlaw-weekly.log 2>&1

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

WEEKLY=""
if [ "${1:-}" = "--weekly-publish" ]; then
  WEEKLY="--weekly-publish"
fi

docker compose --profile local up -d
python scripts/init_infra.py
explainlaw daily $WEEKLY

# Crontab: ./scripts/install-cron.sh
# Бэкфилл дельт: ./scripts/backfill.sh  или  LIMIT=500 ./scripts/backfill.sh
