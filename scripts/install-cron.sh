#!/usr/bin/env bash
# Установка crontab для ExplainLaw (§7.1, §11)
# Использование: ./scripts/install-cron.sh [--user]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DAILY="$ROOT/scripts/daily.sh"
BACKFILL="$ROOT/scripts/backfill.sh"
LOG_DIR="${EXPLAINLAW_LOG_DIR:-/var/log}"

mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="$ROOT/logs" && mkdir -p "$LOG_DIR"

CRON_BLOCK="# ExplainLaw pipeline (managed by install-cron.sh)
0 8 * * * $DAILY >> $LOG_DIR/explainlaw-daily.log 2>&1
0 9 * * 1 $DAILY --weekly-publish >> $LOG_DIR/explainlaw-weekly.log 2>&1
# Воскресенье 03:00 — догон дельт поправок (без лимита; долго)
0 3 * * 0 LIMIT=500 $BACKFILL >> $LOG_DIR/explainlaw-backfill.log 2>&1
"

if [ "${1:-}" = "--print" ]; then
  printf '%s\n' "$CRON_BLOCK"
  exit 0
fi

TMP="$(mktemp)"
(crontab -l 2>/dev/null | grep -v 'ExplainLaw pipeline' | grep -v "$DAILY" | grep -v "$BACKFILL" || true) > "$TMP"
printf '%s\n' "$CRON_BLOCK" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "Crontab updated. Logs: $LOG_DIR"
crontab -l | grep -A3 'ExplainLaw' || true
