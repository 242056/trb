#!/bin/sh
# Entrypoint для regulatory-legal-acts-cron:
# 1) генерирует crontab из env
# 2) опционально сразу прогоняет job (CRON_RUN_ON_START)
# 3) запускает supercronic (логи job → stdout + /app/logs/cron.log)
set -eu

export PATH="/usr/local/bin:${PATH}"
export TZ="${TZ:-${CRON_TIMEZONE:-Europe/Moscow}}"

CRONTAB_PATH="${CRONTAB_PATH:-/tmp/explainlaw.crontab}"
EXPLAINLAW_BIN="${EXPLAINLAW_BIN:-/usr/local/bin/explainlaw}"
CRON_RUN_WRAPPER="${CRON_RUN_WRAPPER:-/app/docker/cron-run.sh}"
CRON_LOG_PATH="${CRON_LOG_PATH:-/app/logs/cron.log}"

mkdir -p "$(dirname "$CRON_LOG_PATH")" /app/logs
chmod +x "$CRON_RUN_WRAPPER" 2>/dev/null || true

echo "[cron] timezone=$TZ log=$CRON_LOG_PATH"
python /app/docker/render_crontab.py > "$CRONTAB_PATH"
echo "[cron] crontab:"
sed 's/^/  /' "$CRONTAB_PATH"
{
  echo "===== cron start $(date '+%Y-%m-%d %H:%M:%S%z') tz=$TZ ====="
  cat "$CRONTAB_PATH"
} >>"$CRON_LOG_PATH"

if [ ! -x /usr/local/bin/supercronic ]; then
  echo "[cron] FATAL: /usr/local/bin/supercronic missing or not executable" >&2
  exit 1
fi
if [ ! -x "$EXPLAINLAW_BIN" ]; then
  echo "[cron] FATAL: $EXPLAINLAW_BIN missing — rebuild image / check pip install" >&2
  exit 1
fi
if [ ! -x "$CRON_RUN_WRAPPER" ]; then
  echo "[cron] FATAL: $CRON_RUN_WRAPPER missing or not executable" >&2
  exit 1
fi

run_on_start="$(echo "${CRON_RUN_ON_START:-false}" | tr '[:upper:]' '[:lower:]')"
if [ "$run_on_start" = "true" ] || [ "$run_on_start" = "1" ] || [ "$run_on_start" = "yes" ]; then
  job="$(echo "${CRON_RUN_ON_START_JOB:-weekly}" | tr '[:upper:]' '[:lower:]')"
  echo "[cron] RUN_ON_START job=$job"
  case "$job" in
    daily)
      "$CRON_RUN_WRAPPER" "$EXPLAINLAW_BIN" daily --process-limit "${PIPELINE_PROCESS_LIMIT:-50}" --fetch-missing "${PIPELINE_FETCH_MISSING_LIMIT:-3}"
      ;;
    weekly)
      "$CRON_RUN_WRAPPER" "$EXPLAINLAW_BIN" publish --mark-published
      ;;
    health)
      "$CRON_RUN_WRAPPER" "$EXPLAINLAW_BIN" health --alert
      ;;
    smoke)
      "$CRON_RUN_WRAPPER" "$EXPLAINLAW_BIN" prod-smoke
      ;;
    *)
      echo "[cron] unknown CRON_RUN_ON_START_JOB=$job (daily|weekly|health|smoke)" >&2
      exit 1
      ;;
  esac
  echo "[cron] RUN_ON_START finished ok"
fi

echo "[cron] starting supercronic (passthrough-logs → docker logs + $CRON_LOG_PATH)"
exec /usr/local/bin/supercronic -passthrough-logs "$CRONTAB_PATH"
