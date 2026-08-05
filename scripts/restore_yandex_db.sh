#!/usr/bin/env bash
# Восстановление дампа explainlaw в Yandex Managed PostgreSQL
# Использование:
#   DATABASE_URL='postgresql://user1:pass@host:6432/regulatory-legal-acts?sslmode=require' \
#   ./scripts/restore_yandex_db.sh explainlaw_backup.dump
set -euo pipefail

DUMP="${1:?Укажите путь к .dump или .sql}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "Задайте DATABASE_URL (postgresql://user:pass@host:6432/db?sslmode=require)"
  exit 1
fi

if [[ "$DUMP" == *.dump ]]; then
  pg_restore --clean --if-exists --no-owner --no-acl -d "$DATABASE_URL" "$DUMP"
elif [[ "$DUMP" == *.sql ]]; then
  psql "$DATABASE_URL" -f "$DUMP"
else
  echo "Поддерживаются только .dump и .sql"
  exit 1
fi

echo "Restore complete. Run: alembic upgrade head (если схема новее дампа)"
