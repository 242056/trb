#!/bin/sh
# Обёртка для supercronic: пишет старт/финиш/exit в /app/logs/cron.log и на stdout.
set -eu

LOG="${CRON_LOG_PATH:-/app/logs/cron.log}"
mkdir -p "$(dirname "$LOG")"

ts() { date '+%Y-%m-%d %H:%M:%S%z'; }

cmd="$*"
echo "[$(ts)] START $cmd" | tee -a "$LOG"
set +e
"$@" >>"$LOG" 2>&1
ec=$?
set -e
if [ "$ec" -eq 0 ]; then
  echo "[$(ts)] OK    $cmd" | tee -a "$LOG"
else
  echo "[$(ts)] FAIL  exit=$ec $cmd" | tee -a "$LOG"
fi
exit "$ec"
