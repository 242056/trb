#!/usr/bin/env bash
# Установка crontab для ExplainLaw (§7.1, §11)
# Использование:
#   ./scripts/install-cron.sh           # локальный docker-compose
#   ./scripts/install-cron.sh --prod    # Yandex PG/Kafka + внешний MinIO
#   ./scripts/install-cron.sh --print
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="local"
if [ "${1:-}" = "--prod" ]; then
  MODE="prod"
  shift || true
fi

LOG_DIR="${EXPLAINLAW_LOG_DIR:-/var/log}"
mkdir -p "$LOG_DIR" 2>/dev/null || { LOG_DIR="$ROOT/logs"; mkdir -p "$LOG_DIR"; }

if [ "$MODE" = "prod" ]; then
  DAILY="$ROOT/scripts/daily_prod.sh"
  BACKFILL="$ROOT/scripts/backfill_prod.sh"
  HEALTH="$ROOT/scripts/health_prod.sh"
  BACKUP="$ROOT/scripts/backup_minio.sh"
  CRON_BLOCK="# ExplainLaw pipeline PROD (managed by install-cron.sh --prod)
0 8 * * * $DAILY >> $LOG_DIR/explainlaw-daily.log 2>&1
0 9 * * 1 $DAILY --weekly-publish >> $LOG_DIR/explainlaw-weekly.log 2>&1
0 3 * * 0 LIMIT=500 $BACKFILL >> $LOG_DIR/explainlaw-backfill.log 2>&1
30 */6 * * * $HEALTH >> $LOG_DIR/explainlaw-health.log 2>&1
0 2 * * 0 $BACKUP >> $LOG_DIR/explainlaw-backup.log 2>&1
"
else
  DAILY="$ROOT/scripts/daily.sh"
  BACKFILL="$ROOT/scripts/backfill.sh"
  CRON_BLOCK="# ExplainLaw pipeline (managed by install-cron.sh)
0 8 * * * $DAILY >> $LOG_DIR/explainlaw-daily.log 2>&1
0 9 * * 1 $DAILY --weekly-publish >> $LOG_DIR/explainlaw-weekly.log 2>&1
0 3 * * 0 LIMIT=500 $BACKFILL >> $LOG_DIR/explainlaw-backfill.log 2>&1
"
fi

if [ "${1:-}" = "--print" ]; then
  printf '%s\n' "$CRON_BLOCK"
  exit 0
fi

TMP="$(mktemp)"
(crontab -l 2>/dev/null | grep -v 'ExplainLaw pipeline' | grep -v "$ROOT/scripts/daily" | grep -v "$ROOT/scripts/backfill" || true) > "$TMP"
printf '%s\n' "$CRON_BLOCK" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "Crontab updated ($MODE). Logs: $LOG_DIR"
crontab -l | grep -A6 'ExplainLaw' || true
